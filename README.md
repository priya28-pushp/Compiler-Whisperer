# AI-Powered Compiler Error Assistant

Paste C, C++, Java or Python code. The tool compiles it, finds the errors, tells you
**which compiler phase** caught each one, explains it in plain English and suggests a fix.

## Features
- **Accounts**: sign up, log in, forgot/reset password (hashed passwords, expiring one-time reset tokens, login rate limiting)
- **Analyzer**: compiles C/C++/Java/Python, names the compiler phase, explains errors in plain English, optional AI fixes
- **Don't Give Me the Answer mode**: a Socratic hint ladder (gentle hint, strong hint, solution) that hides the answer until you ask
- **Root-cause analysis**: groups cascading diagnostics, shows the root error first and which messages may disappear
- **Concept Cards**: every error comes with the concept behind it, why it matters, a wrong/right example and related topics to review
- **Compiler Lab**: tokens -> parse tree -> three-address code -> optimisation -> stack-machine code (`lab.py`)
- **Dashboard**: error stats by phase, most repeated mistakes, activity chart, history with reopen (`auth.py`)

## How it works (compiler-design view)
| Stage | What the project does |
|-------|-----------------------|
| Lexical analysis | Own regex tokenizer (`lexical_report`) builds the token stream, flags unterminated strings |
| Syntax analysis | Bracket-balance check with a stack + errors reported by the real compiler |
| Semantic analysis | Undeclared names, type mismatches, missing returns (from gcc / javac) |
| Linking | `undefined reference` errors |
| Error-explanation engine | Rule base (regex -> phase, explanation, fix) + optional AI model for custom explanations and corrected code |

## Run it
```bash
python -m venv venv
venv\Scripts\activate          # Windows   (Mac/Linux: source venv/bin/activate)
pip install -r requirements.txt
python app.py
```
Open http://127.0.0.1:5000

Compilers needed on your PATH: `gcc`/`g++` (C, C++), `javac` (Java). Python needs nothing extra.

### Optional: turn on AI explanations
```bash
set ANTHROPIC_API_KEY=your_key_here        # Windows (Mac/Linux: export ...)
python app.py
```
Without a key the app still works using the built-in rule engine.

## Notes
- After compiling, the program is **run** (5 second limit, output capped) and its output is shown. Runtime crashes (division by zero, bad index, infinite loop...) are explained too. Use the *Program input* box for programs that read input.
- Running executes your own code on your own computer. Never expose this app on the public internet as-is; set `ALLOW_RUN=0` to switch running off, or run it inside Docker.
- Password reset runs in demo mode: no email server, so the link is shown on screen and printed in the terminal. Set `DEMO_MODE=0` to hide it.
- Layout: `app.py` (analyzer + routes), `auth.py` (accounts, history, stats), `lab.py` (mini compiler), `knowledge.py` (hints, concept cards, root-cause logic), `static/` (pages).
