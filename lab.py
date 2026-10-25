"""Compiler Lab: a small but real compiler front-end + back-end for arithmetic statements.
tokens -> recursive-descent parser -> AST -> three-address code -> constant folding -> stack code."""
import re
from flask import Blueprint, jsonify, request
from auth import login_required

bp = Blueprint("lab", __name__)
TOK = re.compile(r"\s*(?:(\d+(?:\.\d+)?)|([A-Za-z_]\w*)|(\S))")
GRAMMAR = ["stmt   -> ID '=' expr | expr", "expr   -> term (('+' | '-') term)*",
           "term   -> factor (('*' | '/') factor)*", "factor -> '-' factor | NUMBER | ID | '(' expr ')'"]


class LabError(Exception):
    def __init__(self, msg, pos):
        super().__init__(msg)
        self.pos = pos


def node(label, kind, kids=None):
    return dict(label=label, kind=kind, kids=kids or [])


def tokenize(src):
    out, i = [], 0
    while i < len(src):
        m = TOK.match(src, i)
        if not m:
            break
        if m.group(1):
            out.append(("NUMBER", m.group(1), m.start(1)))
        elif m.group(2):
            out.append(("ID", m.group(2), m.start(2)))
        elif m.group(3) in "+-*/()=":
            out.append(("OPERATOR", m.group(3), m.start(3)))
        else:
            raise LabError(f"Illegal character '{m.group(3)}' (lexical error)", m.start(3))
        i = m.end()
    return out


class Parser:
    def __init__(self, toks, n):
        self.t, self.i, self.n = toks, 0, n

    def peek(self):
        return self.t[self.i] if self.i < len(self.t) else ("EOF", "", self.n)

    def eat(self, v=None):
        k, x, p = self.peek()
        if v and x != v:
            raise LabError(f"Expected '{v}' but found {'end of input' if k == 'EOF' else repr(x)} (syntax error)", p)
        self.i += 1
        return k, x, p

    def stmt(self):
        if len(self.t) > 1 and self.t[0][0] == "ID" and self.t[1][1] == "=":
            name = self.eat()[1]
            self.eat("=")
            tree = node("=", "ASSIGN", [node(name, "ID"), self.expr()])
        else:
            tree = self.expr()
        k, x, p = self.peek()
        if k != "EOF":
            raise LabError(f"Unexpected '{x}' after a complete expression (syntax error)", p)
        return tree

    def expr(self):
        left = self.term()
        while self.peek()[1] in ("+", "-"):
            op = self.eat()[1]
            left = node(op, "OP", [left, self.term()])
        return left

    def term(self):
        left = self.factor()
        while self.peek()[1] in ("*", "/"):
            op = self.eat()[1]
            left = node(op, "OP", [left, self.factor()])
        return left

    def factor(self):
        k, x, p = self.peek()
        if x == "-" and k == "OPERATOR":
            self.eat()
            return node("neg", "NEG", [self.factor()])
        if k in ("NUMBER", "ID"):
            self.eat()
            return node(x, k)
        if x == "(":
            self.eat()
            e = self.expr()
            self.eat(")")
            return e
        raise LabError(f"Expected a number, variable or '(' but found {'end of input' if k == 'EOF' else repr(x)} (syntax error)", p)


def fmt(v):
    return str(int(v)) if v == int(v) else str(round(v, 6))


def fold(n):
    """Constant folding + simple algebraic identities (x*1, x+0, x*0)."""
    kids = [fold(k) for k in n["kids"]]
    if n["kind"] == "ASSIGN":
        return node(n["label"], "ASSIGN", [n["kids"][0], kids[1]])
    if n["kind"] == "NEG" and kids[0]["kind"] == "NUMBER":
        return node(fmt(-float(kids[0]["label"])), "NUMBER")
    if n["kind"] == "OP":
        a, b = kids
        num = lambda k, v: k["kind"] == "NUMBER" and float(k["label"]) == v
        if a["kind"] == b["kind"] == "NUMBER" and not (n["label"] == "/" and float(b["label"]) == 0):
            x, y = float(a["label"]), float(b["label"])
            return node(fmt({"+": x + y, "-": x - y, "*": x * y, "/": x / y if y else 0}[n["label"]]), "NUMBER")
        if (n["label"] == "+" and num(b, 0)) or (n["label"] == "-" and num(b, 0)) or (n["label"] in "*/" and num(b, 1)):
            return a
        if (n["label"] == "+" and num(a, 0)) or (n["label"] == "*" and num(a, 1)):
            return b
        if n["label"] == "*" and (num(a, 0) or num(b, 0)):
            return node("0", "NUMBER")
    return node(n["label"], n["kind"], kids)


def tac(n, out, c):
    if n["kind"] in ("NUMBER", "ID"):
        return n["label"]
    if n["kind"] == "ASSIGN":
        out.append(f"{n['kids'][0]['label']} = {tac(n['kids'][1], out, c)}")
        return None
    if n["kind"] == "NEG":
        a = tac(n["kids"][0], out, c)
        c[0] += 1
        out.append(f"t{c[0]} = -{a}")
        return f"t{c[0]}"
    a, b = tac(n["kids"][0], out, c), tac(n["kids"][1], out, c)
    c[0] += 1
    out.append(f"t{c[0]} = {a} {n['label']} {b}")
    return f"t{c[0]}"


def stack(n, out):
    if n["kind"] in ("NUMBER", "ID"):
        out.append(f"PUSH {n['label']}")
    elif n["kind"] == "ASSIGN":
        stack(n["kids"][1], out)
        out.append(f"STORE {n['kids'][0]['label']}")
    elif n["kind"] == "NEG":
        stack(n["kids"][0], out)
        out.append("NEG")
    else:
        stack(n["kids"][0], out)
        stack(n["kids"][1], out)
        out.append({"+": "ADD", "-": "SUB", "*": "MUL", "/": "DIV"}[n["label"]])


def gen(tree):
    t, s = [], []
    r = tac(tree, t, [0])
    if r is not None:
        t.append(f"result = {r}")
    stack(tree, s)
    return t, s


@bp.post("/api/lab")
@login_required
def lab():
    src = (request.get_json(silent=True) or {}).get("expr", "").rstrip()
    if not src.strip() or len(src) > 200:
        return jsonify(ok=False, error="Type an expression such as  x = 2 * (3 + 4) - y", pos=0)
    try:
        toks = tokenize(src)
        tree = Parser(toks, len(src)).stmt()
    except LabError as e:
        return jsonify(ok=False, error=str(e), pos=e.pos)
    opt = fold(tree)
    t1, s1 = gen(tree)
    t2, s2 = gen(opt)
    return jsonify(ok=True, tokens=[dict(kind=k, text=x) for k, x, _ in toks], grammar=GRAMMAR, ast=tree, opt_ast=opt,
                   tac=t1, opt_tac=t2, stack=s1, opt_stack=s2)
