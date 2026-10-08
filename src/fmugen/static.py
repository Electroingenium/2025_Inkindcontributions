"""Reading a model's source code to find its results, without running it.

`fmugen init` (without --probe) uses this instead of calling the model: it parses the
source of the function or step method with `ast` and looks at what it returns and which
attributes it assigns, and at type annotations. Nothing here calls into the model's code.
What can't be known this way (array sizes, results built at runtime, code without Python
source) is reported back so the config can say so.
"""
import ast
import dataclasses
import inspect
import textwrap
import types
import typing

PRIMITIVE_TYPES = {float: "Real", int: "Integer", bool: "Boolean", str: "String"}
ARRAY_ANNOTATIONS = ("ndarray", "Tensor", "jax.Array", "tf.Tensor", "list[", "List[", "Sequence[", "numpy")
MAX_DEPTH = 6   # how far to follow self.method() calls


@dataclasses.dataclass
class Returned:
    """What a function or method returns, as far as the code tells."""
    names: list = dataclasses.field(default_factory=list)   # output names, in order
    sources: dict = dataclasses.field(default_factory=dict)  # name -> "return" / "return:<key>"
    types: dict = dataclasses.field(default_factory=dict)    # name -> FMI type (when known)
    array: bool = False      # the whole result is an array (size unknown)
    unknown: str = None      # why the result couldn't be read, if it couldn't
    may_be_none: bool = False   # some return statements return None (simpy's Environment.run)


def function_node(fn):
    """The ast.FunctionDef of fn, or None when there's no Python source (C extensions, builtins)."""
    fn = inspect.unwrap(getattr(fn, "__func__", fn))
    try:
        source = textwrap.dedent(inspect.getsource(fn))
        tree = ast.parse(source)
    except (OSError, TypeError, SyntaxError, IndentationError):
        return None
    node = tree.body[0] if tree.body else None
    return node if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) else None


def _own_nodes(node):
    """All nodes inside a function body, not entering nested functions, classes or lambdas."""
    nested = (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef, ast.Lambda)

    def walk(items):   # in source order
        for item in items:
            if not isinstance(item, nested):
                yield item
                yield from walk(ast.iter_child_nodes(item))

    yield from walk(node.body)


ARRAY_CALLS = {"array", "asarray", "zeros", "ones", "empty", "full", "arange", "linspace", "eye", "tensor",
               "zeros_like", "ones_like", "empty_like", "full_like", "roll", "stack", "concatenate", "list", "tuple"}
NUMBER_CALLS = {"float", "int", "abs", "round", "sqrt", "exp", "log", "log10", "log2", "sin", "cos", "tan",
                "asin", "acos", "atan", "atan2", "sinh", "cosh", "tanh", "pow", "hypot", "floor", "ceil", "radians",
                "degrees", "isclose"}
OTHER_CALLS = {"dict", "set", "frozenset", "deque", "defaultdict", "OrderedDict", "Counter", "open", "Lock",
               "RLock", "Thread", "Queue", "Event", "object"}


def _literal_type(node, namespace=None):
    """What an assigned/returned expression obviously is: "Boolean", "String", "Real" (arithmetic, a
    number literal, math functions), "array", "other" (not an FMI value: dicts, sets, objects), or None
    (not obvious from the code)."""
    if isinstance(node, ast.Constant):
        if isinstance(node.value, bool):
            return "Boolean"
        if isinstance(node.value, str):
            return "String"
        if node.value is None:
            return "none"
        return "Real" if isinstance(node.value, (int, float)) else None
    if isinstance(node, ast.BinOp):   # a * b, x ** 2; "a" + b is a string, [a] * n a list
        kinds = {_literal_type(node.left, namespace), _literal_type(node.right, namespace)}
        if kinds & {"String", "array", "other"}:
            return None
        return "Real"
    if isinstance(node, ast.UnaryOp) and isinstance(node.op, (ast.USub, ast.UAdd)):
        return "Real"
    if isinstance(node, (ast.Compare, ast.BoolOp)) or isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.Not):
        return "Boolean"   # a > b, a and b, not a (BoolOp of non-bools is rare in model code)
    if isinstance(node, (ast.List, ast.ListComp, ast.Tuple)):
        return "array"
    if isinstance(node, (ast.Dict, ast.DictComp, ast.Set, ast.SetComp, ast.Lambda, ast.GeneratorExp)):
        return "other"
    if isinstance(node, ast.Call):
        name = node.func.attr if isinstance(node.func, ast.Attribute) else getattr(node.func, "id", "")
        if name in ARRAY_CALLS:
            return "array"
        if name in NUMBER_CALLS:
            return "Real"
        if name in OTHER_CALLS:
            return "other"
        target = _resolve(node.func, namespace or {})
        if isinstance(target, type) and target not in (int, float, bool, str, complex):
            return "other"   # an instance of a class: an object, not a number
    return None


def _hint_type(hint):
    return PRIMITIVE_TYPES.get(unwrap_optional(hint))


OPTIONAL_NAMES = {"float": float, "int": int, "bool": bool, "str": str}


def written_globals(module):
    """Names of module-level variables that a function of `module` rebinds (`global X; X = ...`):
    state kept outside the model object, e.g. pythermalcomfort's PRE_SHIV."""
    try:
        tree = ast.parse(inspect.getsource(module))
    except (OSError, TypeError, SyntaxError, UnicodeDecodeError):
        return []
    found = []
    for fn in ast.walk(tree):
        if not isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        declared = {n for node in ast.walk(fn) if isinstance(node, ast.Global) for n in node.names}
        assigned = {t.id for node in ast.walk(fn) if isinstance(node, (ast.Assign, ast.AugAssign, ast.AnnAssign))
                    for t in (node.targets if isinstance(node, ast.Assign) else [node.target])
                    if isinstance(t, ast.Name)}
        found += [n for n in sorted(declared & assigned) if n not in found]
    return found


def unwrap_optional(hint):
    """X for Optional[X] / X | None / Union[X, None] (also written as strings), else hint unchanged."""
    if isinstance(hint, str):
        text = hint.replace(" ", "").replace("typing.", "")
        if text.startswith("Optional[") and text.endswith("]"):
            text = text[len("Optional["):-1]
        parts = [t for t in text.split("|") if t != "None"]
        return OPTIONAL_NAMES.get(parts[0], hint) if len(parts) == 1 else hint
    if typing.get_origin(hint) in (typing.Union, types.UnionType):
        rest = [a for a in typing.get_args(hint) if a is not type(None)]
        if len(rest) == 1:
            return rest[0]
    return hint


def _is_array_hint(hint):
    return hint is not None and any(a in repr(hint) for a in ARRAY_ANNOTATIONS)


def _fields_of(hint):
    """Field names and types of a NamedTuple, TypedDict or dataclass type, else None."""
    if not isinstance(hint, type):
        return None
    if issubclass(hint, tuple) and hasattr(hint, "_fields"):
        names = list(hint._fields)
    elif typing.is_typeddict(hint) or dataclasses.is_dataclass(hint):
        names = list(getattr(hint, "__annotations__", {}))
    else:
        return None
    try:
        hints = typing.get_type_hints(hint)
    except Exception:
        hints = getattr(hint, "__annotations__", {})
    return names, {n: _hint_type(hints.get(n)) for n in names if _hint_type(hints.get(n))}


def returned(fn, namespace=None, attributes=None):
    """What fn returns: dict keys, tuple positions, NamedTuple/dataclass fields, or a single value.
    `attributes` ({attr: kind}, for a method) gives the kind of a returned self.attr."""
    try:
        hint = typing.get_type_hints(inspect.unwrap(getattr(fn, "__func__", fn))).get("return")
    except Exception:
        hint = None
    fields = _fields_of(hint)
    if fields:
        names, types = fields
        return Returned(names, {n: f"return:{n}" for n in names}, types)
    if hint is type(None):
        return Returned()
    if _hint_type(hint):
        return Returned(["y"], {"y": "return"}, {"y": _hint_type(hint)})
    if _is_array_hint(hint):
        return Returned(["y"], {"y": "return"}, array=True)

    node = function_node(fn)
    if node is None:
        return Returned(unknown="no Python source to read (a C extension or a compiled model)")
    namespace = namespace or getattr(inspect.unwrap(getattr(fn, "__func__", fn)), "__globals__", {})
    self_name = node.args.args[0].arg if node.args.args else None
    dict_vars = _local_dicts(node)
    arg_names = {a.arg for a in [*node.args.posonlyargs, *node.args.args, *node.args.kwonlyargs]} - {self_name}

    found = {}   # local variables: x = a * b
    for item in _own_nodes(node):
        if isinstance(item, ast.Assign) and len(item.targets) == 1 and isinstance(item.targets[0], ast.Name):
            value = item.value
            if isinstance(value, ast.Name):   # y = x: x's kind (an argument, or an earlier local)
                value_kind = f"arg:{value.id}" if value.id in arg_names else _merge(found.get(value.id, []))
            else:
                value_kind = _literal_type(value)
            found.setdefault(item.targets[0].id, []).append(value_kind)
        elif isinstance(item, ast.AugAssign) and isinstance(item.target, ast.Name):
            found.setdefault(item.target.id, []).append(None)   # x += ...: its kind stays that of x = ...
    local_kinds = {name: _merge(kinds) for name, kinds in found.items()}

    def kind(value):   # an argument returned as it is takes that argument's type ("arg:<name>")
        if isinstance(value, ast.Name) and value.id in arg_names:
            return f"arg:{value.id}"
        if isinstance(value, ast.Name) and value.id in local_kinds:
            return local_kinds[value.id]
        if attributes is not None and isinstance(value, ast.Attribute) and isinstance(value.value, ast.Name)                 and value.value.id == self_name:
            return attributes.get(value.attr)
        return _literal_type(value)

    shapes, none = [], False
    for item in _own_nodes(node):
        if not isinstance(item, ast.Return):
            continue
        value = item.value
        if value is None or isinstance(value, ast.Constant) and value.value is None:
            none = True
            continue
        if isinstance(value, ast.Name) and value.id == self_name:
            continue
        if isinstance(value, ast.Dict) and _str_keys(value):
            leaves = _dict_leaves(value, kind)
            shapes.append(("keys", list(leaves), leaves))
        elif isinstance(value, ast.Name) and value.id in dict_vars:
            shapes.append(("keys", dict_vars[value.id], {}))
        elif isinstance(value, ast.Tuple):
            shapes.append(("tuple", [f"y{i}" for i in range(len(value.elts))], {}))
        elif isinstance(value, ast.Call) and _fields_of(_resolve(value.func, namespace)):
            names, types = _fields_of(_resolve(value.func, namespace))
            shapes.append(("fields", names, types))
        else:
            shapes.append(("single", ["y"], {"y": kind(value)}))
    if not shapes:
        return Returned()
    kinds = {kind for kind, _, _ in shapes}
    if kinds == {"keys"} or kinds == {"fields"}:
        names, types = [], {}
        for _, keys, key_types in shapes:   # union over several returns, in order
            names += [k for k in keys if k not in names]
            types.update({k: t for k, t in key_types.items() if t})
        return Returned(names, {n: f"return:{n}" for n in names}, types)
    if len(kinds) == 1 and kinds <= {"tuple", "single"} and len({len(n) for _, n, _ in shapes}) == 1:
        kind, names, types = shapes[0]
        sources = {n: f"return:{i}" for i, n in enumerate(names)} if kind == "tuple" else {"y": "return"}
        return Returned(names, sources, {k: t for k, t in types.items() if t}, may_be_none=none)
    return Returned(unknown="its return statements return different shapes")


def _dict_leaves(node, kind, prefix="", depth=0):
    """{name: type} for a dict literal, with dict literals inside it named with dots: {"zone": {"T": t}} -> zone.T"""
    leaves = {}
    for key, value in zip(_str_keys(node), node.values):
        if isinstance(value, ast.Dict) and _str_keys(value) and depth < 3:
            leaves.update(_dict_leaves(value, kind, f"{prefix}{key}.", depth + 1))
        else:
            leaves[prefix + key] = kind(value)
    return leaves


def _str_keys(node):
    keys = [k.value for k in node.keys if isinstance(k, ast.Constant) and isinstance(k.value, str)]
    return keys if len(keys) == len(node.keys) and all(k.isidentifier() for k in keys) else []


def _local_dicts(node):
    """{variable: [keys]} for `v = {...}` / `v = dict()` plus `v["k"] = ...` in the function."""
    dicts = {}
    for item in _own_nodes(node):
        if isinstance(item, ast.Assign) and len(item.targets) == 1 and isinstance(item.targets[0], ast.Name):
            value = item.value
            if isinstance(value, ast.Dict) and (_str_keys(value) or not value.keys):
                dicts[item.targets[0].id] = list(_str_keys(value))
            elif isinstance(value, ast.Call) and isinstance(value.func, ast.Name) and value.func.id == "dict" \
                    and not value.args:
                dicts[item.targets[0].id] = [k.arg for k in value.keywords if k.arg]
    for item in _own_nodes(node):
        if isinstance(item, ast.Assign):
            for target in item.targets:
                if isinstance(target, ast.Subscript) and isinstance(target.value, ast.Name) \
                        and target.value.id in dicts and isinstance(target.slice, ast.Constant) \
                        and isinstance(target.slice.value, str) and target.slice.value.isidentifier() \
                        and target.slice.value not in dicts[target.value.id]:
                    dicts[target.value.id].append(target.slice.value)
    return {k: v for k, v in dicts.items() if v}


def _resolve(node, namespace):
    """The object a Name / dotted Attribute refers to in namespace, or None (no import, no call)."""
    parts = []
    while isinstance(node, ast.Attribute):
        parts.insert(0, node.attr)
        node = node.value
    if not isinstance(node, ast.Name) or node.id not in namespace:
        return None
    obj = namespace[node.id]
    for part in parts:
        obj = inspect.getattr_static(obj, part, None)
        if obj is None:
            return None
    return obj


def assigned_attributes(cls, method_name, depth=MAX_DEPTH, raw=False):
    """{attribute: kind} that method_name sets on self, following self.other() calls. The kind is
    "Boolean", "String", "Real", "array", "other" (not an FMI value) or None (not obvious)."""
    kinds, seen = {}, set()

    def visit(name, level):
        if name in seen or level > depth:
            return
        seen.add(name)
        method = inspect.getattr_static(cls, name, None)
        node = function_node(method) if method is not None else None
        if node is None or not node.args.args:
            return
        self_name = node.args.args[0].arg
        namespace = getattr(inspect.unwrap(getattr(method, "__func__", method)), "__globals__", {})
        for item in _own_nodes(node):
            targets = item.targets if isinstance(item, ast.Assign) else \
                [item.target] if isinstance(item, (ast.AugAssign, ast.AnnAssign)) else []
            for target in targets:
                for t in (target.elts if isinstance(target, ast.Tuple) else [target]):
                    base = t.value if isinstance(t, ast.Subscript) else t
                    if isinstance(base, ast.Attribute) and isinstance(base.value, ast.Name) \
                            and base.value.id == self_name:
                        value = item.value if isinstance(item, ast.Assign) and t is target else None
                        if isinstance(t, ast.Subscript):
                            value = None   # self.x[i] = ...: x is a container, its kind comes from elsewhere
                        ref = _attribute_ref(value, self_name) if value is not None else None
                        if isinstance(item, ast.AugAssign) and t is base:   # self.x += dx: x has dx's kind
                            found = _literal_type(item.value, namespace)
                            found = "Real" if not isinstance(item.op, ast.Add) or found == "Real" else None
                        else:
                            found = ("ref", ref) if ref else _literal_type(value, namespace) if value is not None else None
                        kinds.setdefault(base.attr, []).append(found)
            if isinstance(item, ast.Call) and isinstance(item.func, ast.Attribute) \
                    and isinstance(item.func.value, ast.Name) and item.func.value.id == self_name:
                visit(item.func.attr, level + 1)

    visit(method_name, 0)
    if raw:
        return kinds
    return {attr: _merge([k for k in found if not isinstance(k, tuple)]) for attr, found in kinds.items()}


COPY_METHODS = {"copy", "clone", "detach", "astype", "reshape", "flatten", "ravel", "tolist", "cpu", "numpy"}


def _attribute_ref(node, self_name):
    """The attribute name if node is self.y, self.y.copy() (and similar) or np.copy(self.y), else None."""
    if isinstance(node, ast.Call):
        if isinstance(node.func, ast.Attribute) and node.func.attr in COPY_METHODS:
            node = node.func.value
        elif isinstance(node.func, ast.Attribute) and node.func.attr == "copy" and len(node.args) == 1:
            node = node.args[0]
    if isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name) and node.value.id == self_name:
        return node.attr
    return None


def class_attributes(cls, method_name):
    """({attr: kind} set by the step method, {attr: kind} set by __init__), with assignments copied
    from other attributes (self.x_prior = self.x.copy()) taking that attribute's kind."""
    step, init = assigned_attributes(cls, method_name, raw=True), assigned_attributes(cls, "__init__", raw=True)

    def kind(attr, seen=()):
        found = []
        for k in step.get(attr, []) + init.get(attr, []):
            if isinstance(k, tuple):
                found.append(kind(k[1], seen + (attr,)) if k[1] not in seen and k[1] != attr else None)
            else:
                found.append(k)
        return _merge(found)

    return {a: kind(a) for a in step}, {a: kind(a) for a in init}


def _merge(found):
    """One kind from all assignments: not-FMI and array win; None placeholders are ignored."""
    for kind in ("other", "array"):
        if kind in found:
            return kind
    known = [k for k in found if k not in (None, "none")]
    return known[0] if known else None


def init_copies(cls):
    """Constructor arguments the constructor stores unchanged as attributes (self.x = x)."""
    node = function_node(inspect.getattr_static(cls, "__init__", None))
    if node is None or not node.args.args:
        return set()
    self_name = node.args.args[0].arg
    copies = set()
    for item in _own_nodes(node):
        if isinstance(item, ast.Assign) and isinstance(item.value, ast.Name):
            for target in item.targets:
                if isinstance(target, ast.Attribute) and isinstance(target.value, ast.Name) \
                        and target.value.id == self_name and target.attr == item.value.id:
                    copies.add(target.attr)
    return copies


def own_properties(cls):
    """{name: FMI type or None} of public properties defined in the model's own package (not read)."""
    package = cls.__module__.split(".")[0]
    found = {}
    for klass in cls.__mro__:
        if klass.__module__.split(".")[0] != package:
            continue
        for name, member in vars(klass).items():
            if isinstance(member, property) and member.fget is not None and not name.startswith("_"):
                try:
                    hint = typing.get_type_hints(member.fget).get("return")
                except Exception:
                    hint = None
                if not _is_array_hint(hint):
                    found.setdefault(name, _hint_type(hint))
    return found


def factory_class(factory):
    """The class a factory function is annotated to return, if any (e.g. `-> torchani.arch.ANI`)."""
    try:
        hint = typing.get_type_hints(factory).get("return")
    except Exception:
        return None
    return hint if isinstance(hint, type) and hint.__module__ != "builtins" else None
