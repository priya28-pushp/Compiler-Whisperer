"""AI-Powered Compiler Error Assistant - Flask backend."""
import json, os, re, shutil, subprocess, sys, tempfile
from flask import Flask, jsonify, redirect, request, send_from_directory, session

import auth, knowledge, lab

app = Flask(__name__, static_folder="static")
_key = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".secret_key")
if not os.path.exists(_key):  # persistent random secret so logins survive restarts
    open(_key, "w").write(os.urandom(32).hex())
app.secret_key = os.getenv("SECRET_KEY") or open(_key).read()
app.config.update(SESSION_COOKIE_SAMESITE="Lax", SESSION_COOKIE_HTTPONLY=True)
app.register_blueprint(auth.bp)
app.register_blueprint(lab.bp)
auth.init_db()
TIMEOUT = 15
MAX_CHARS = 20000

# language -> (file extension, compile command builder). Code is compiled, never run.
LANGS = {
    "c": ("c", lambda f, o: ["gcc", "-Wall", "-o", o, f]),
    "cpp": ("cpp", lambda f, o: ["g++", "-Wall", "-o", o, f]),
    "java": ("java", lambda f, o: ["javac", f]),
    "python": ("py", lambda f, o: [sys.executable, "-m", "py_compile", f]),
}

# ---------------------------------------------------------------- Phase 1: lexical analysis
KEYWORDS = (r"\b(?:int|float|double|char|void|long|short|if|else|for|while|do|return|break|continue|"
            r"class|public|private|static|new|def|import|from|include|using|namespace|struct|switch|"
            r"case|try|catch|except|print|true|false|None|True|False)\b")
TOKEN_SPEC = [
    ("COMMENT", r"//[^\n]*|/\*[\s\S]*?\*/|#[^\n]*"),
    ("STRING", r'"(?:\\.|[^"\\\n])*"|\'(?:\\.|[^\'\\\n])*\''),
    ("NUMBER", r"\d+(?:\.\d+)?"),
    ("KEYWORD", KEYWORDS),
    ("IDENT", r"[A-Za-z_]\w*"),
    ("OPERATOR", r"[+\-*/%=<>!&|^~?:]+"),
    ("PUNCT", r"[(){}\[\];,.]"),
    ("SKIP", r"\s+"),
    ("UNKNOWN", r"."),
]
TOKEN_RE = re.compile("|".join(f"(?P<{n}>{p})" for n, p in TOKEN_SPEC))


def lexical_report(code, lang):
    """Tokenise the source, count token kinds, find unterminated strings and unbalanced brackets."""
    tokens, counts, issues = [], {}, []
    for m in TOKEN_RE.finditer(code):
        kind, text = m.lastgroup, m.group()
        line = code.count("\n", 0, m.start()) + 1
        if kind == "COMMENT" and text.startswith("#") and lang in ("c", "cpp"):
            kind = "DIRECTIVE"
        if kind == "SKIP":
            continue
        counts[kind] = counts.get(kind, 0) + 1
        if kind == "UNKNOWN" and text in "\"'":
            issues.append(dict(line=line, message="missing terminating quote", title="Unterminated string",
                               explanation="A string literal was opened with a quote but never closed on the same line.",
                               fix="Add the matching closing quote at the end of the string."))
        if kind not in ("COMMENT", "DIRECTIVE"):
            tokens.append((kind, text, line))
    # stack-based bracket matching (a tiny taste of syntax analysis)
    pairs, stack = {")": "(", "]": "[", "}": "{"}, []
    for kind, text, line in tokens:
        if kind != "PUNCT":
            continue
        if text in "([{":
            stack.append((text, line))
        elif text in pairs:
            if stack and stack[-1][0] == pairs[text]:
                stack.pop()
            else:
                issues.append(dict(line=line, message=f"unmatched '{text}'", title="Unmatched bracket",
                                   explanation=f"This '{text}' has no matching opening bracket.",
                                   fix="Remove it, or add the missing opening bracket earlier."))
    for text, line in stack:
        close = {"(": ")", "[": "]", "{": "}"}[text]
        issues.append(dict(line=line, message=f"unclosed '{text}'", title="Unclosed bracket",
                           explanation=f"This '{text}' is never closed, so the parser runs off the end of the file.",
                           fix=f"Add the matching '{close}' where the block should end."))
    return dict(counts=counts, tokens=[dict(kind=k, text=t, line=l) for k, t, l in tokens[:80]],
                total=len(tokens), issues=issues)


# ---------------------------------------------------------------- Phase 2: run the real compiler
RUN_ENABLED = os.getenv("ALLOW_RUN", "1") != "0"   # set ALLOW_RUN=0 to turn program execution off
RUN_TIMEOUT = 5
OUT_LIMIT = 10000


def _clip(t):
    return t[:OUT_LIMIT], len(t) > OUT_LIMIT


def execute(lang, tmp, path, exe, name, stdin):
    """Run the freshly compiled program (5 s limit, output capped) and capture stdout/stderr."""
    cmd = {"c": [exe], "cpp": [exe], "java": ["java", "-cp", tmp, name], "python": [sys.executable, "-u", path]}[lang]
    r = dict(ran=True, stdout="", stderr="", exit_code=0, timed_out=False, truncated=False, note="")
    try:
        p = subprocess.run(cmd, input=stdin, capture_output=True, text=True, encoding="utf-8", errors="replace",
                           timeout=RUN_TIMEOUT, cwd=tmp, env=dict(os.environ, PYTHONIOENCODING="utf-8"))
        r.update(stdout=p.stdout, stderr=p.stderr.replace(tmp + os.sep, ""), exit_code=p.returncode)
    except subprocess.TimeoutExpired as e:
        out = e.stdout or ""
        r.update(stdout=out.decode("utf-8", "replace") if isinstance(out, bytes) else out, timed_out=True, exit_code=-1)
    except FileNotFoundError:
        r.update(ran=False, note=f"Could not start the program ('{cmd[0]}' was not found).")
    (r["stdout"], t1), (r["stderr"], t2) = _clip(r["stdout"]), _clip(r["stderr"])
    r["truncated"] = t1 or t2
    return r


def runtime_errors(lang, r):
    """Turn a crashed/failed run into explainable errors."""
    if not r or not r.get("ran"):
        return []
    out, err = [], r["stderr"]
    if r["timed_out"]:
        out = [dict(line=None, col=None, severity="error", message="program timed out: possible infinite loop")]
    elif lang == "python" and "Traceback" in err:
        out = parse_errors("python", err)
    elif lang == "java":
        m = re.search(r'Exception in thread "[^"]*" (\S+?)(?::\s*(.*))?$', err, re.M)
        if m:
            ln = re.search(r"\(\w+\.java:(\d+)\)", err)
            out = [dict(line=int(ln[1]) if ln else None, col=None, severity="error",
                        message=f"{m.group(1)}: {m.group(2) or ''}".strip())]
    rc = r["exit_code"]
    if not out and not r["timed_out"] and (rc < 0 or rc >= 0xC0000000):
        out = [dict(line=None, col=None, severity="error", message=f"program crashed (segmentation fault), exit code {rc}")]
    for e in out:
        e["runtime"] = True
    return out


def compile_code(lang, code, run=False, stdin=""):
    """Returns (ok, compiler_output, run_result). ok is None when the compiler could not run."""
    ext, build = LANGS[lang]
    tmp = tempfile.mkdtemp(prefix="cea_")
    try:
        name = "main"
        if lang == "java":
            m = re.search(r"public\s+(?:final\s+)?class\s+(\w+)", code)
            name = m.group(1) if m else "Main"
        path = os.path.join(tmp, f"{name}.{ext}")
        with open(path, "w", encoding="utf-8") as f:
            f.write(code)
        exe = os.path.join(tmp, "prog.exe" if os.name == "nt" else "prog")
        try:
            p = subprocess.run(build(path, exe), cwd=tmp, capture_output=True, text=True, timeout=TIMEOUT)
        except FileNotFoundError:
            return None, f"The compiler for {lang.upper()} was not found on this machine.", None
        except subprocess.TimeoutExpired:
            return None, "Compilation timed out.", None
        ok, output = p.returncode == 0, (p.stderr + p.stdout).replace(tmp + os.sep, "")
        res = execute(lang, tmp, path, exe, name, stdin) if (ok and run and RUN_ENABLED) else None
        return ok, output, res
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


GCC_RE = re.compile(r"^(?P<file>[^\s:]+):(?P<line>\d+):(?:(?P<col>\d+):)?\s*(?P<sev>fatal error|error|warning):\s*(?P<msg>.+)$", re.M)
JAVAC_RE = re.compile(r"^(?P<file>\S+\.java):(?P<line>\d+):\s*(?P<sev>error|warning):\s*(?P<msg>.+)$", re.M)
LD_RE = re.compile(r"undefined reference to [`'](?P<sym>[^'`]+)'")
PY_LINE_RE = re.compile(r'File ".*?", line (\d+)')
PY_ERR_RE = re.compile(r"^(\w*(?:Error|Exception)):\s*(.*)$", re.M)


def parse_errors(lang, out):
    errs = []
    if lang in ("c", "cpp", "java"):
        for m in (GCC_RE if lang != "java" else JAVAC_RE).finditer(out):
            col = m.groupdict().get("col")
            errs.append(dict(line=int(m["line"]), col=int(col) if col else None,
                             severity="warning" if m["sev"] == "warning" else "error", message=m["msg"]))
        for m in LD_RE.finditer(out):
            errs.append(dict(line=None, col=None, severity="error", message=f"undefined reference to '{m['sym']}'"))
    else:
        m, lines = PY_ERR_RE.search(out), PY_LINE_RE.findall(out)
        if m:
            errs.append(dict(line=int(lines[-1]) if lines else None, col=None, severity="error",
                             message=f"{m.group(1)}: {m.group(2)}"))
    if not errs and out.strip():
        errs.append(dict(line=None, col=None, severity="error", message=out.strip().splitlines()[0]))
    for e in errs:
        e["message"] = e["message"].replace("\u2018", "'").replace("\u2019", "'")
    return errs


# ---------------------------------------------------------------- Phase 3: explanation engine
# (regex, compiler phase, title, plain-English explanation, how to fix)
RULES = [
    (r"timed out", "Runtime", "Program never finished",
     "Your program kept running past the 5 second limit, which almost always means an infinite loop.",
     "Check every loop: the variable in the while/for condition must change, and the condition must eventually become false."),
    (r"ZeroDivisionError|ArithmeticException|division by zero|/ by zero", "Runtime", "Division by zero",
     "The program tried to divide a number by zero, which has no answer, so it stopped.",
     "Check the divisor before dividing: if it is 0, handle that case separately."),
    (r"IndexError|IndexOutOfBounds|out of range", "Runtime", "Index outside the list or array",
     "You asked for an item at a position that does not exist. Positions start at 0, so a list of 5 items ends at index 4.",
     "Keep the index between 0 and length - 1. A loop condition like i <= n is a common culprit; use i < n."),
    (r"segmentation fault|program crashed", "Runtime", "Program crashed (bad memory access)",
     "The program touched memory it does not own, for example an array index far out of bounds or a NULL pointer.",
     "Check array indexes and pointers before using them, and make sure pointers are initialised."),
    (r"NullPointerException", "Runtime", "Null reference",
     "You used an object variable that does not point to any object yet.",
     "Create the object with new before using it, or check for null first."),
    (r"EOFError|InputMismatchException|NoSuchElementException", "Runtime", "Program asked for input that was not given",
     "Your program waited for the user to type something, but no input was supplied.",
     "Type the values into the 'Program input' box before running, one value per line."),
    (r"ValueError|NumberFormatException", "Runtime", "Value in the wrong format",
     "The program tried to convert text into a number, but the text was not a valid number.",
     "Make sure the input really is a number before converting, or catch the error."),
    (r"KeyError", "Runtime", "Missing dictionary key",
     "You looked up a key that is not in the dictionary.",
     "Check the key exists first (if key in d) or use d.get(key)."),
    (r"FileNotFoundError|FileNotFoundException", "Runtime", "File not found",
     "The program tried to open a file that does not exist in its working folder.",
     "Check the file name and path, or create the file first."),
    (r"RecursionError|StackOverflowError", "Runtime", "Recursion never stops",
     "A function kept calling itself until the call stack ran out of room.",
     "Add a base case that stops the recursion, and make sure each call moves towards it."),
    (r"No such file or directory|package .* does not exist", "Preprocess", "File or package not found",
     "The compiler tried to include or import something it could not locate.",
     "Check the spelling of the header/package name and that it is installed or in the same folder."),
    (r"expected ';'|';' expected|expected ',' or ';'", "Syntax", "Missing semicolon",
     "Statements in C, C++ and Java end with a semicolon. The parser finished a statement and did not find one.",
     "Add ';' at the end of the statement. The real mistake is often on the line above the one reported."),
    (r"expected ':'", "Syntax", "Missing colon",
     "Python needs a colon after if, for, while, def and class headers.",
     "Add ':' at the end of that line."),
    (r"IndentationError|expected an indented block|unexpected indent|unindent", "Syntax", "Indentation problem",
     "Python uses indentation to group statements, and this block is indented inconsistently or not at all.",
     "Indent the body of the block by 4 spaces and do not mix tabs with spaces."),
    (r"was never closed|reached end of file while parsing|expected '[)}\]]'|expected declaration or statement at end|unmatched|unterminated|missing terminating|unexpected EOF",
     "Syntax", "Unclosed bracket or quote",
     "A bracket, brace or quote was opened and never closed, so the parser hit the end of the file mid-structure.",
     "Match every ( [ { and quote with its closing partner. Editors that highlight matching brackets help."),
    (r"implicit declaration of function", "Semantic", "Function used before it is declared",
     "You called a function the compiler has never seen declared. This usually means a missing header.",
     "Add the right #include (for example <stdio.h> for printf) or declare the function above main."),
    (r"undeclared|not declared in this scope|cannot find symbol|NameError|is not defined", "Semantic", "Unknown name",
     "You used a name that was never declared. Typos, wrong capitalisation and missing imports are the usual cause.",
     "Check the spelling, declare the variable before using it, and make sure the right include/import is present."),
    (r"incompatible types|incompatible pointer|invalid conversion|cannot convert|invalid operands|TypeError|cannot be converted",
     "Semantic", "Type mismatch",
     "A value of one type was used where another type is required, for example a string assigned to an int.",
     "Change the variable's type, convert the value explicitly (a cast), or fix the expression."),
    (r"control reaches end|missing return statement|non-void", "Semantic", "Missing return value",
     "A function that promises to return a value can finish without returning anything.",
     "Add a return statement on every path through the function."),
    (r"uninitialized|might not have been initialized", "Semantic", "Variable used before it has a value",
     "The variable is read before anything was assigned to it, so its value is unpredictable.",
     "Give the variable an initial value when you declare it."),
    (r"unused variable|unused parameter", "Semantic", "Unused variable",
     "A variable is declared but never used. This is only a warning.",
     "Delete the variable or use it."),
    (r"format '.*' expects|format specifies", "Semantic", "Wrong printf format",
     "The format specifier (like %d) does not match the type of the argument you passed.",
     "Use %d for int, %f for float/double, %s for strings, %c for char."),
    (r"redefinition|already defined|redeclared|has already been declared", "Semantic", "Declared twice",
     "The same name is declared more than once in the same scope.",
     "Rename one of them or remove the duplicate declaration."),
    (r"undefined reference", "Linking", "Undefined reference (linker error)",
     "The code compiled, but the linker could not find the body of a function you call. Often main is misspelled or a source file/library is missing.",
     "Define the function, link the missing file or library, and check that 'main' is spelled correctly."),
    (r"invalid syntax|SyntaxError|expected expression|expected identifier|illegal start of|not a statement|class, interface, or enum expected|expected .* before",
     "Syntax", "Syntax error",
     "The code does not follow the grammar of the language at this point, so the parser could not build a valid structure.",
     "Look at the reported line and the line just before it for a missing symbol, extra symbol or misspelled keyword."),
]


def explain(e):
    for pat, phase, title, why, fix in RULES:
        if re.search(pat, e["message"], re.I):
            e.update(phase=phase, title=title, explanation=why, fix=fix)
            return e
    e.update(phase="Syntax", title="Compiler error",
             explanation="The compiler rejected this part of the code. Read its message together with the highlighted line.",
             fix="Check the line reported and the line above it for typos or missing symbols.")
    return e


def ai_assist(lang, code, errors):
    """Optional: ask Claude for friendlier explanations plus a corrected program."""
    key = os.getenv("ANTHROPIC_API_KEY")
    if not key or not errors:
        return None
    try:
        import anthropic
        listing = "\n".join(f"{i}. line {e['line']}: {e['message']}" for i, e in enumerate(errors))
        msg = anthropic.Anthropic(api_key=key).messages.create(
            model=os.getenv("CLAUDE_MODEL", "claude-sonnet-5-5"), max_tokens=2000,
            system=("You are a patient programming tutor for beginners. Reply with JSON only, no markdown: "
                    '{"explanations":[{"index":0,"explanation":"2 simple sentences on why it happened",'
                    '"fix":"1 simple sentence on how to fix it"}],"fixed_code":"the full corrected program"}'),
            messages=[{"role": "user", "content": f"Language: {lang}\n\nCode:\n{code}\n\nCompiler errors:\n{listing}"}])
        text = "".join(b.text for b in msg.content if b.type == "text").strip()
        text = re.sub(r"^```(?:json)?|```$", "", text, flags=re.M).strip()
        return json.loads(text)
    except Exception as exc:  # network, key or JSON problems: fall back to the rule engine
        return {"_error": str(exc)[:200]}


# ---------------------------------------------------------------- routes
def guarded(name):
    return send_from_directory("static", name) if session.get("uid") else redirect("/login")


@app.get("/")
def index():
    return guarded("index.html")


@app.get("/lab")
def lab_page():
    return guarded("lab.html")


@app.get("/dashboard")
def dashboard_page():
    return guarded("dashboard.html")


@app.get("/login")
def login_page():
    return redirect("/") if session.get("uid") else send_from_directory("static", "auth.html")


@app.post("/api/analyze")
@auth.login_required
def analyze():
    data = request.get_json(force=True, silent=True) or {}
    lang, code = data.get("language", ""), data.get("code", "")
    if lang not in LANGS:
        return jsonify(error="Unsupported language."), 400
    if not code.strip():
        return jsonify(error="Paste some code first."), 400
    if len(code) > MAX_CHARS:
        return jsonify(error="Code is too long (20,000 character limit)."), 400

    lex = lexical_report(code, lang)
    ok, raw, run_res = compile_code(lang, code, bool(data.get("run", True)), str(data.get("stdin", ""))[:5000])
    missing = ok is None
    errors = [] if missing else parse_errors(lang, raw) + runtime_errors(lang, run_res)
    if missing:  # no compiler installed: fall back to our own lexical/bracket checks
        errors = [dict(line=i["line"], col=None, severity="error", message=i["message"]) for i in lex["issues"]]
    errors = [explain(e) for e in errors]
    for e in errors:
        if e.get("runtime"):
            e["phase"] = "Runtime"
    if missing:
        for e, i in zip(errors, lex["issues"]):
            e.update(phase="Syntax", title=i["title"], explanation=i["explanation"], fix=i["fix"])

    src = code.splitlines()
    for e in errors:
        e["source"] = src[e["line"] - 1] if e["line"] and e["line"] <= len(src) else ""

    ai = ai_assist(lang, code, [e for e in errors if e["severity"] == "error"])
    ai_info = dict(used=False, fixed_code=None, error=None)
    if ai and "_error" in ai:
        ai_info["error"] = ai["_error"]
    elif ai:
        real = [e for e in errors if e["severity"] == "error"]
        for x in ai.get("explanations", []):
            if isinstance(x.get("index"), int) and 0 <= x["index"] < len(real):
                real[x["index"]]["explanation"] = x.get("explanation", real[x["index"]]["explanation"])
                real[x["index"]]["fix"] = x.get("fix", real[x["index"]]["fix"])
        ai_info.update(used=True, fixed_code=ai.get("fixed_code"))

    analysis = knowledge.enrich(errors)
    if run_res is None:
        note = ""
        if not missing and not ok:
            note = "Fix the compile errors first. Your program's output will appear here once it compiles."
        elif not RUN_ENABLED:
            note = "Running programs is switched off on this server."
        run_res = dict(ran=False, note=note)
    result = dict(ok=bool(ok), compiler_missing=missing, raw=raw, errors=errors, lexer=lex, ai=ai_info, run=run_res, analysis=analysis)
    auth.save_history(session["uid"], lang, code, result)
    return jsonify(result)


if __name__ == "__main__":
    app.run(host="127.0.0.1", port=5000, debug=False)
