"""Teaching layer: hint ladder, concept cards and root-cause analysis for compiler errors."""
import re

DEFAULT_CASCADE = "The compiler loses track of the program's structure"
# title -> (concept, gentle hint, strong hint, why it matters, wrong example, right example, related concepts, cascade note)
_E = [
 ("Missing semicolon", "Statement terminators",
  "Look at line {line} and the statement just before it. Does every statement finish the same way?",
  "Which symbol tells C, C++ and Java where a statement ends? Check the line above the one reported.",
  "The parser uses ';' to know where one statement stops and the next begins.",
  "int x = 5\nint y = 6;", "int x = 5;\nint y = 6;", ["Statements", "Parsing", "Tokens"], "Parser loses the statement boundary"),
 ("Missing colon", "Block headers in Python",
  "Look at the very end of line {line}. How does Python mark the start of an indented block?",
  "Lines starting with if, for, while, def and class all end with one punctuation mark. Is it there?",
  "The colon tells Python that an indented block of code follows.",
  "def greet(name)\n    print(name)", "def greet(name):\n    print(name)", ["Blocks", "Functions", "Indentation"], "Python cannot tell where the block starts"),
 ("Indentation problem", "Indentation as syntax",
  "Compare how far line {line} is indented with the line above it.",
  "In Python every line of one block must start at exactly the same column. Is the body indented under its header?",
  "Python has no braces, so indentation is the only thing that groups statements.",
  "if x > 0:\nprint(x)", "if x > 0:\n    print(x)", ["Blocks", "Whitespace", "Python syntax"], "Block structure is lost"),
 ("Unclosed bracket or quote", "Balanced delimiters",
  "Count the ( [ { and quote marks you opened. Does each one have a partner? Start near line {line}.",
  "Read from the top and tick off each opening bracket when you meet its closing one. Which one is left over?",
  "Brackets and quotes come in pairs. One missing partner makes the parser read on until the end of the file.",
  'print("hi"', 'print("hi")', ["Brackets", "Strings", "Nesting"], "Everything after it is read as part of the unfinished group"),
 ("Syntax error", "Grammar of a language",
  "Read line {line} slowly, then the line before it. Is anything missing, extra or misspelled?",
  "Compare it with a similar line that works. Which symbol or keyword is different?",
  "Every language has grammar rules, and code must follow them just like sentences must.",
  "for (i = 0; i < 5 i++)", "for (i = 0; i < 5; i++)", ["Grammar", "Keywords", "Parsing"], "The parser cannot build a valid structure from here"),
 ("Compiler error", "Reading compiler messages",
  "Read the compiler's message and look at line {line} and the line above it.",
  "Which word in the message names a symbol, type or keyword? Find it in your code.",
  "Compiler messages always point at the place where it gave up, which may be just after the real mistake.",
  "(depends on the error)", "(depends on the error)", ["Diagnostics", "Debugging"], ""),
 ("File or package not found", "Includes and imports",
  "Look at the include or import on line {line}. Is the name spelled exactly right?",
  "Standard headers use <angle brackets>; your own files use quotes and must sit in the project folder.",
  "The compiler can only use code it can locate. A wrong name means the whole file is missing.",
  "#include <stdoi.h>", "#include <stdio.h>", ["#include", "Imports", "Libraries"], "Everything from that library is also missing"),
 ("Function used before it is declared", "Declarations and headers",
  "Which function is called on line {line}? Has the compiler been told that it exists?",
  "Library functions live in headers. Which #include does this function need?",
  "C and C++ read top to bottom, so a function must be declared before it is called.",
  'int main() { printf("hi"); }', '#include <stdio.h>\nint main() { printf("hi"); }', ["Header files", "Prototypes", "#include"], ""),
 ("Unknown name", "Declarations and scope",
  "Look at the name used on line {line}. Where did you first declare it?",
  "Compare its spelling and capital letters with the declaration. Is it declared before this line, in the same scope?",
  "Compilers never guess. A name must be declared, spelled identically, and visible from where you use it.",
  'int total = 0;\nprintf("%d", totl);', 'int total = 0;\nprintf("%d", total);', ["Variables", "Scope", "Imports"], "Every later use of the same name fails too"),
 ("Type mismatch", "Data types",
  "What type does the variable on line {line} expect, and what type of value are you giving it?",
  "Compare the type on the left of '=' with the value on the right. Do they match, or do you need a conversion?",
  "The compiler checks that values and operations are type-compatible before it lets the program run.",
  'int age = "twenty";', "int age = 20;", ["Data types", "Type checking", "Casting"], ""),
 ("Missing return value", "Return statements",
  "Follow every possible path through the function that ends near line {line}. Does each path end with a return?",
  "What happens if the if-condition is false? What does the function hand back then?",
  "A function that promises a value must deliver one on every path, or the caller receives garbage.",
  "int f(int x) {\n    if (x > 0) return 1;\n}", "int f(int x) {\n    if (x > 0) return 1;\n    return 0;\n}", ["Functions", "Control flow", "Return types"], ""),
 ("Variable used before it has a value", "Initialisation",
  "Find the variable used on line {line}. What value does it hold before that line?",
  "Local variables do not start at zero. Where is this one first given a value?",
  "Reading a variable that was never assigned gives unpredictable results that change from run to run.",
  "int sum;\nsum += 5;", "int sum = 0;\nsum += 5;", ["Variables", "Initialisation", "Garbage values"], ""),
 ("Unused variable", "Clean code",
  "A variable around line {line} is created but never read. Do you actually need it?",
  "Either use the variable somewhere or delete it.",
  "Unused variables are often a sign of a typo or a forgotten step, so compilers warn about them.",
  "int unused = 3;", "(remove the line, or use the variable)", ["Variables", "Warnings"], ""),
 ("Wrong printf format", "Format specifiers",
  "Check the % codes in the string on line {line}. Do they match the values that follow?",
  "%d is for int, %f for float/double, %s for strings, %c for char. Which one does not match?",
  "printf trusts your format string. A wrong code prints garbage or crashes.",
  'printf("%d", 3.5);', 'printf("%f", 3.5);', ["printf", "Data types", "Format strings"], ""),
 ("Declared twice", "Scope and naming",
  "Search for the name used on line {line}. Is it declared more than once in the same block?",
  "A name can be declared only once per scope. Rename one, or turn the second declaration into a plain assignment.",
  "If two things share a name, the compiler cannot know which one you mean.",
  "int x = 1;\nint x = 2;", "int x = 1;\nx = 2;", ["Scope", "Variables", "Naming"], ""),
 ("Undefined reference (linker error)", "Linking",
  "Your code compiled, so the problem comes later. Which function does the linker say it cannot find?",
  "The compiler only checks that a function is declared; the linker needs its body. Is it defined, spelled right, and its file or library included?",
  "Building a program has two stages: compiling each file, then linking them together. This error is from the second stage.",
  "int mian() { return 0; }", "int main() { return 0; }", ["Linker", "main()", "Libraries"], ""),
 ("Program never finished", "Loop termination",
  "Look at your loops. What makes each one stop?",
  "Does the variable in the loop condition change inside the loop, in the right direction?",
  "A loop only ends when its condition becomes false. If nothing changes the condition, it runs forever.",
  "while i < 5:\n    print(i)", "while i < 5:\n    print(i)\n    i += 1", ["Loops", "Conditions", "Infinite loops"], ""),
 ("Division by zero", "Edge cases and exceptions",
  "Which line divides? On line {line}, could the divisor ever be zero?",
  "Check the divisor with an if before dividing.",
  "Division by zero has no answer, so the program stops instead of guessing.",
  "avg = total / count   # count is 0", "avg = total / count if count else 0", ["Exceptions", "Conditions", "Edge cases"], ""),
 ("Index outside the list or array", "Zero-based indexing",
  "Look at the index used on line {line}. How many items does the list have?",
  "Valid positions run from 0 to length minus 1. Is your loop going one step too far?",
  "Positions start at 0, so a list of 5 items ends at index 4. Asking for position 5 goes past the end.",
  "for (i = 0; i <= 5; i++) a[i]   // a has 5 items", "for (i = 0; i < 5; i++) a[i]", ["Arrays", "Loops", "Off-by-one errors"], ""),
 ("Program crashed (bad memory access)", "Memory safety",
  "The program stopped abruptly. Which pointers or array indexes are used near where the output ends?",
  "Is any pointer NULL or uninitialised, or any index outside the array, at the moment it is used?",
  "Touching memory you do not own makes the operating system stop your program immediately.",
  "int *p = NULL;\n*p = 5;", "int x;\nint *p = &x;\n*p = 5;", ["Pointers", "Arrays", "Memory"], ""),
 ("Null reference", "Object creation",
  "Which object is used on line {line}? Was it ever created?",
  "Create the object with new before using it, or check for null first.",
  "A variable that holds null points at nothing, so calling a method on it fails.",
  "String s = null;\ns.length();", 'String s = "hi";\ns.length();', ["Objects", "null", "References"], ""),
 ("Program asked for input that was not given", "Standard input",
  "Does your program ask the user to type something? Where?",
  "Open 'Program input' under the editor and type the values there, one per line.",
  "Programs that read input wait for it. If nothing is supplied, they fail at the first read.",
  "age = int(input())   # nothing typed", "age = int(input())   # type 18 in the Program input box", ["Input", "Standard input"], ""),
 ("Value in the wrong format", "Type conversion",
  "Which text is turned into a number on line {line}? What does it actually contain?",
  "A conversion like int('abc') cannot work. Make sure the text is only digits before converting.",
  "Converting text to a number only works if the text really looks like that number.",
  'int("abc")', 'int("42")', ["Type conversion", "Input validation", "Exceptions"], ""),
 ("Missing dictionary key", "Dictionaries",
  "Which key is looked up on line {line}? Was it ever added?",
  "Check that the key exists first (if key in d) or use d.get(key).",
  "A dictionary only knows the keys that were stored in it.",
  "d = {'a': 1}\nd['b']", "d = {'a': 1}\nd.get('b', 0)", ["Dictionaries", "Keys", "Defaults"], ""),
 ("File not found", "File handling",
  "Which file does line {line} try to open? Does it exist in the program's folder?",
  "Check the file name, extension and path, or create the file first.",
  "Opening a file needs the exact path. A small typo means the file cannot be found.",
  'open("data.txt")   # file missing', 'open("data.txt")   # file exists in the folder', ["Files", "Paths", "Exceptions"], ""),
 ("Recursion never stops", "Base case in recursion",
  "Look at the function that calls itself. Which condition makes it stop?",
  "Does every call move closer to that stopping condition?",
  "A recursive function needs a base case, otherwise the calls pile up until memory runs out.",
  "def f(n):\n    return f(n - 1)", "def f(n):\n    if n == 0:\n        return 0\n    return f(n - 1)", ["Recursion", "Base case", "Call stack"], ""),
]
KB = {t: dict(concept=c, gentle=g, strong=s, why=w, bad=b, good=gd, related=r, cascade=ca) for t, c, g, s, w, b, gd, r, ca in _E}

# title -> (error in simple words, definition of the concept, mini explanation of the example)
_X = {
 "Missing semicolon": ("You forgot to end a statement with a semicolon.",
  "A statement terminator is the symbol that marks the end of one instruction.",
  "In the wrong example the first line has no ';', so the compiler reads both lines as one long statement. Adding ';' separates them."),
 "Missing colon": ("You left out the colon at the end of a block header.",
  "A block header (if, for, while, def, class) introduces the indented lines that belong to it.",
  "def greet(name) needs ':' at the end, otherwise Python does not know the indented line is its body."),
 "Indentation problem": ("The lines in this block are not lined up correctly.",
  "In Python, the spaces at the start of a line decide which block that line belongs to.",
  "print(x) must be indented under the if line, otherwise Python sees an if with an empty body."),
 "Unclosed bracket or quote": ("A bracket or quote was opened but never closed.",
  "Balanced delimiters means every opening ( [ { or quote mark has a matching closing one.",
  'print("hi" opens a bracket that is never closed, so the compiler keeps looking for ")" until the file ends.'),
 "Syntax error": ("The code is not written in the shape the language expects.",
  "Grammar is the set of rules that says which symbols may follow which.",
  "A for header needs ';' between its three parts. The wrong version is missing one, so the parser cannot read it."),
 "Compiler error": ("The compiler could not understand part of your code.",
  "A diagnostic is the message a compiler gives about a problem it found.",
  "Read the message, find the line it names, and check that line and the one above it."),
 "File or package not found": ("The file or library you tried to use cannot be found.",
  "An include or import tells the compiler to bring in code from another file.",
  "stdoi.h is a typo of stdio.h, so the compiler searches for a file that does not exist."),
 "Function used before it is declared": ("You used a function the compiler has not been told about.",
  "A declaration introduces a name and its type to the compiler before it is used.",
  "printf is declared in stdio.h. Without the include, the compiler has never heard of it."),
 "Unknown name": ("You used a name that was never created, or spelled it differently.",
  "Scope is the part of a program where a declared name can be used.",
  "total was declared, but totl was not, so the compiler cannot find it. One missing letter is enough."),
 "Type mismatch": ("A value of the wrong kind was given to a variable.",
  "A data type is the kind of value a variable can hold, such as a whole number, a decimal or text.",
  'age is an int, so it holds numbers. The text "twenty" is a string, so the compiler refuses it.'),
 "Missing return value": ("A function can finish without giving anything back.",
  "A return statement sends a value from a function back to the code that called it.",
  "If x is not greater than 0, the wrong version reaches the end without returning. The right version always returns."),
 "Variable used before it has a value": ("You used a variable that never received a value.",
  "Initialisation means giving a variable its first value at the moment it is created.",
  "sum starts with leftover memory, so adding 5 to it gives an unpredictable result. Starting it at 0 fixes that."),
 "Unused variable": ("You created a variable and never used it.",
  "Dead code is code that exists but has no effect on the result.",
  "unused is given the value 3 but nothing ever reads it. Delete it, or use it."),
 "Wrong printf format": ("The % code does not match the kind of value you printed.",
  "A format specifier is the % code in printf that says how to display a value.",
  "%d prints whole numbers, but 3.5 is a decimal, so it needs %f."),
 "Declared twice": ("You created the same name twice in the same place.",
  "Scope and naming rules say a name can be declared only once in a block.",
  "The second 'int x' tries to create x again. Writing 'x = 2' just changes the existing one."),
 "Undefined reference (linker error)": ("A function was used but its code was never found.",
  "Linking is the final build step that joins your compiled files and libraries into one program.",
  "The linker looks for a function named main. mian is a typo, so it finds nothing to start."),
 "Program never finished": ("Your program keeps running and never stops.",
  "A loop repeats code for as long as its condition stays true.",
  "i never changes in the wrong version, so i < 5 stays true forever. i += 1 moves it towards 5."),
 "Division by zero": ("The program tried to divide by zero.",
  "An edge case is an unusual input, like zero or an empty list, that your code must handle.",
  "If count is 0 the division has no answer. The right version checks count first."),
 "Index outside the list or array": ("You asked for a position that does not exist.",
  "Zero-based indexing means the first item is at position 0, so the last is at length minus 1.",
  "An array of 5 items has positions 0 to 4. i <= 5 reaches position 5, which is past the end."),
 "Program crashed (bad memory access)": ("The program touched memory it is not allowed to use.",
  "A pointer is a variable that stores the memory address of another value.",
  "p is NULL, so it points at nothing, and writing through it crashes. The right version points p at a real variable."),
 "Null reference": ("You used an object that was never created.",
  "null means a variable points to no object at all.",
  "s is null, so s.length() has nothing to measure. Giving s a value fixes it."),
 "Program asked for input that was not given": ("The program waited for typed input, but none was given.",
  "Standard input is the stream of text a program reads from the user.",
  "int(input()) needs a typed value. Type it into the Program input box before running."),
 "Value in the wrong format": ("Text could not be turned into a number.",
  "Type conversion changes a value from one type to another, such as text to a number.",
  'int("abc") fails because abc is not made of digits. int("42") works.'),
 "Missing dictionary key": ("You looked up a key that is not in the dictionary.",
  "A dictionary stores values under keys, and you get a value back by asking for its key.",
  "d['b'] fails because only 'a' was stored. d.get('b', 0) returns 0 instead of failing."),
 "File not found": ("The program could not find the file it tried to open.",
  "A file path says exactly where a file lives on the disk.",
  "open('data.txt') looks in the program's folder. If the file is not there, it fails."),
 "Recursion never stops": ("A function keeps calling itself forever.",
  "A base case is the simple situation where a recursive function stops calling itself.",
  "The wrong f never checks for a stopping point. The right one returns when n reaches 0."),
}
assert set(_X) == set(KB), set(KB) ^ set(_X)
for _t, (_s, _d, _x) in _X.items():
    KB[_t].update(simple=_s, define=_d, explain=_x)
DEFAULT = KB["Compiler error"]
ALIAS = {"Unmatched bracket": "Unclosed bracket or quote", "Unclosed bracket": "Unclosed bracket or quote",
         "Unterminated string": "Unclosed bracket or quote"}
SYMBOL_RE = re.compile(r"'(\w+)'")


def _k(title):
    return KB.get(ALIAS.get(title, title), DEFAULT)


def concept_of(title):
    return _k(title)["concept"]


def _line(e):
    return e["line"] or 10 ** 9


def enrich(errors):
    """Attach hint ladder + concept card to every error, then work out which error is the root cause.
    Re-orders `errors` in place (root first) and returns an analysis summary (or None)."""
    for e in errors:
        k = _k(e["title"])
        where = f"line {e['line']}" if e["line"] else "the reported spot"
        e["hints"] = dict(gentle=k["gentle"].replace("line {line}", where), strong=k["strong"].replace("line {line}", where))
        e["card"] = dict(kind=e["phase"], title=e["title"], concept=k["concept"], simple=k["simple"], why=k["why"], define=k["define"], bad=k["bad"], good=k["good"],
                     explain=k["explain"], related=k["related"])
        e["role"] = "warning" if e["severity"] == "warning" else "independent"

    hard = [e for e in errors if e["severity"] != "warning" and not e.get("runtime")]
    if not hard:
        return None
    parent, syn = {}, [e for e in hard if e["phase"] in ("Syntax", "Preprocess")]
    if syn:  # a syntax error confuses the parser, so everything after it may be a false alarm
        root = min(syn, key=_line)
        for e in hard:
            if e is not root and _line(e) >= _line(root):
                parent[id(e)] = root
    else:    # semantic errors: repeats of the same bad name are one mistake, not many
        root, first = min(hard, key=_line), {}
        for e in sorted(hard, key=_line):
            m = SYMBOL_RE.search(e["message"])
            if m:
                key = (e["title"], m.group(1))
                if key in first:
                    parent[id(e)] = first[key]
                else:
                    first[key] = e
    for e in hard:
        if id(e) in parent:
            e["role"] = "cascade"
    for p in parent.values():
        p["role"] = "root"

    def bucket(e):
        if e is root: return 0
        if e in hard: return 2 if e["role"] == "cascade" else 1
        return 4 if e["severity"] == "warning" else 3
    errors.sort(key=lambda e: (bucket(e), _line(e)))
    for e in errors:
        if id(e) in parent:
            e["cascade_of"] = errors.index(parent[id(e)])

    n = len(parent)
    where = f"line {root['line']}" if root["line"] else "the first error"
    A = dict(hard=len(hard), cascade_count=n, headline="")
    if n:
        s = "s" if n > 1 else ""
        A["headline"] = (f"Fix {where} first, then recompile. {n} other message{s} {'are' if n > 1 else 'is'} "
                         "probably a side-effect and may disappear.")
        A["chain"] = [f"{where[0].upper() + where[1:]}: {root['title']}", _k(root["title"])["cascade"] or DEFAULT_CASCADE,
                      f"{n} later message{s} may look wrong"]
    elif len(hard) > 1:
        A["headline"] = "These errors look independent. Fix them from the top and recompile as you go."
    return A
