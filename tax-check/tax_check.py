#!/usr/bin/env python3
"""Double-check a prepared federal tax return with a local model. Nothing leaves this Mac."""
import argparse
import ast
import datetime
import json
import operator
import re
import subprocess
import sys
import urllib.error
import urllib.request
from pathlib import Path

import tax_2025

HERE = Path(__file__).resolve().parent
REVIEWER_PROMPT = HERE / "reviewer-prompt.md"
SERVER = "http://127.0.0.1:11434"
MODEL = "qwen3.6:35b-a3b"
# Qwen's recommended thinking-mode settings for precise tasks
SAMPLING = {"temperature": 0.6, "top_p": 0.95, "top_k": 20, "min_p": 0.0}
MIN_CHARS_PER_FILE = 50
# SSNs and bank numbers: 000-12-3456, 000 12 3456, 8 to 17 digits in a row, or a spaced-out form box
ID_NUMBER = re.compile(r"(?<![\d,.])(?:\d{3}([- ])\d{2}\1\d{4}|\d{8,17}|(?<!\d )\d(?: \d){7,16}(?! \d))(?!\d|[.,]\d)")
TOO_LONG = (
    "\nThese documents are too long for the model to read at once ({detail}).\n"
    "Remove pages that aren't the federal return (cover letter, state return, e-file forms) and try again.\n"
    "In Preview: View > Thumbnails, select those pages, press Delete, then File > Export as PDF."
)

TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "tax_2025",
            "description": "Exact 2025 Form 1040 line 16 tax using the IRS Tax Table and the Qualified Dividends and Capital Gain Tax Worksheet.",
            "parameters": {
                "type": "object",
                "properties": {
                    "filing_status": {"type": "string", "enum": tax_2025.FILING_STATUSES},
                    "taxable_income": {"type": "number", "description": "Form 1040 line 15"},
                    "qualified_dividends_and_capital_gain": {
                        "type": "number",
                        "description": "Line 3a plus net long-term capital gain (0 if none)",
                    },
                },
                "required": ["filing_status", "taxable_income", "qualified_dividends_and_capital_gain"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "calculate",
            "description": "Evaluate an arithmetic expression exactly. Numbers without commas. Supports + - * / parentheses, min(), max(), round().",
            "parameters": {
                "type": "object",
                "properties": {"expression": {"type": "string", "description": "e.g. 85000 + 1200 + 1500 - 15750"}},
                "required": ["expression"],
            },
        },
    },
]

ARITHMETIC = {ast.Add: operator.add, ast.Sub: operator.sub, ast.Mult: operator.mul, ast.Div: operator.truediv}
FUNCTIONS = {"min": min, "max": max, "round": round}


def evaluate(node):
    if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)):
        return node.value
    if isinstance(node, ast.BinOp) and type(node.op) in ARITHMETIC:
        return ARITHMETIC[type(node.op)](evaluate(node.left), evaluate(node.right))
    if isinstance(node, ast.UnaryOp) and isinstance(node.op, (ast.USub, ast.UAdd)):
        value = evaluate(node.operand)
        return -value if isinstance(node.op, ast.USub) else value
    if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id in FUNCTIONS:
        return FUNCTIONS[node.func.id](*[evaluate(arg) for arg in node.args])
    raise ValueError("only numbers, + - * /, parentheses, min, max, and round are allowed")


def run_tool(name, arguments):
    try:
        args = json.loads(arguments or "{}")
        if name == "tax_2025":
            return json.dumps(tax_2025.line_16_tax(**args))
        if name == "calculate":
            return str(round(evaluate(ast.parse(args["expression"], mode="eval").body), 2))
        return f"Unknown tool: {name}"
    except Exception as error:
        return f"Error: {error!r}"


def mask_id_number(match):
    digits = re.sub(r"\D", "", match.group())
    return "X" * (len(digits) - 4) + digits[-4:]


def read_document(path):
    if path.suffix.lower() == ".pdf":
        text = subprocess.run(
            ["pdftotext", "-layout", str(path), "-"], check=True, capture_output=True, text=True
        ).stdout
    else:
        text = path.read_text()
    if len(text.strip()) < MIN_CHARS_PER_FILE:
        sys.exit(
            f"{path.name} has almost no readable text. It's probably a scan or a photo.\n"
            "Ask your accountant for the PDF their tax software produced, or type the numbers into a .txt file."
        )
    text = ID_NUMBER.sub(mask_id_number, text)
    text = re.sub(r"(?: ?\.){3,}", " ...", text)  # dot leaders like ". . . . ."
    text = re.sub(r"[ \t]{4,}", "    ", text)
    text = re.sub(r"[ \t]+\n", "\n", text)
    return re.sub(r"\n{3,}", "\n\n", text).strip()


def build_request(return_file, source_files):
    parts = [f'<document kind="prepared return" file="{return_file.name}">\n{read_document(return_file)}\n</document>']
    parts += [
        f'<document kind="source document" file="{f.name}">\n{read_document(f)}\n</document>'
        for f in source_files
    ]
    if source_files:
        task = "Review the prepared return above. Compare it against the source documents and check everything in your checklist."
    else:
        task = (
            "Review the prepared return above and check everything in your checklist. "
            "No source documents (W-2s, 1099s) were provided, so say which checks that limits."
        )
    return [
        {"role": "system", "content": REVIEWER_PROMPT.read_text()},
        {"role": "user", "content": "\n\n".join(parts) + "\n\n" + task},
    ]


class Progress:
    def __init__(self):
        self.thinking_tokens = 0
        self.calculations = 0
        self.answering = False

    def show(self):
        if self.answering:
            self.answering = False
            print()
        calculations = f"{self.calculations} calculation{'' if self.calculations == 1 else 's'}"
        print(f"\r\033[KThinking... ({self.thinking_tokens:,} tokens, {calculations})", end="", flush=True)


def stream_turn(messages, progress):
    body = json.dumps({"model": MODEL, "messages": messages, "tools": TOOLS, "stream": True, **SAMPLING}).encode()
    request = urllib.request.Request(f"{SERVER}/v1/chat/completions", body, {"Content-Type": "application/json"})
    reasoning, content, tool_calls = [], [], {}
    with urllib.request.urlopen(request, timeout=900) as response:
        for raw_line in response:
            line = raw_line.decode().strip()
            if not line.startswith("data: ") or line == "data: [DONE]":
                continue
            choices = json.loads(line[len("data: "):]).get("choices") or [{}]
            if choices[0].get("finish_reason") == "length":
                sys.exit(TOO_LONG.format(detail="the model ran out of room while working"))
            delta = choices[0].get("delta") or {}
            if delta.get("reasoning_content"):
                reasoning.append(delta["reasoning_content"])
                progress.thinking_tokens += 1
                progress.show()
            for call in delta.get("tool_calls") or []:
                slot = tool_calls.setdefault(call["index"], {"id": "", "name": "", "arguments": ""})
                slot["id"] += call.get("id") or ""
                slot["name"] += (call.get("function") or {}).get("name") or ""
                slot["arguments"] += (call.get("function") or {}).get("arguments") or ""
            if delta.get("content"):
                if not progress.answering:
                    progress.answering = True
                    print("\r\033[K", end="")
                content.append(delta["content"])
                print(delta["content"], end="", flush=True)
    return "".join(reasoning), "".join(content), [tool_calls[i] for i in sorted(tool_calls)]


def get_reply(messages):
    """Runs the model, answering its tool calls, until it gives a final answer. Returns (work log, answer)."""
    progress = Progress()
    work_log = []
    try:
        while True:
            reasoning, content, tool_calls = stream_turn(messages, progress)
            work_log.append(reasoning)
            if not tool_calls:
                messages.append({"role": "assistant", "content": content})
                print()
                return "\n\n".join(work_log), content
            messages.append({
                "role": "assistant",
                "content": content,
                "reasoning_content": reasoning,
                "tool_calls": [
                    {"id": c["id"], "type": "function", "function": {"name": c["name"], "arguments": c["arguments"]}}
                    for c in tool_calls
                ],
            })
            for call in tool_calls:
                result = run_tool(call["name"], call["arguments"])
                progress.calculations += 1
                progress.show()
                work_log.append(f"**{call['name']}** `{call['arguments']}` -> `{result}`")
                messages.append({"role": "tool", "tool_call_id": call["id"], "content": result})
    except urllib.error.HTTPError as error:
        body = error.read().decode()
        details = (json.loads(body) if body.startswith("{") else {}).get("error") or {}
        if details.get("type") == "exceed_context_size_error":
            sys.exit(TOO_LONG.format(detail=f"{details['n_prompt_tokens']:,} tokens, limit {details['n_ctx']:,}"))
        sys.exit(f"\nThe local model server returned an error:\n{body}")
    except urllib.error.URLError:
        sys.exit(
            f"\nCan't reach the local model server at {SERVER}.\n"
            f"Start llama-server with the {MODEL} model (see README.md) and try again."
        )


def main():
    parser = argparse.ArgumentParser(
        description="Double-check a federal tax return your accountant prepared, using a local model."
    )
    parser.add_argument("tax_return", type=Path, help="the return your accountant prepared (PDF or text)")
    parser.add_argument(
        "source_documents", type=Path, nargs="*", help="optional W-2s, 1099s, 1098s, etc. to compare against"
    )
    args = parser.parse_args()

    for path in [args.tax_return, *args.source_documents]:
        if not path.is_file():
            sys.exit(f"File not found: {path}")

    messages = build_request(args.tax_return, args.source_documents)
    print("Reading your documents (the first run also loads the model, about a minute)...", end="", flush=True)
    work_log, answer = get_reply(messages)

    report_path = args.tax_return.parent / f"{args.tax_return.stem}-review-{datetime.datetime.now():%Y-%m-%d-%H%M}.md"
    reviewed = "\n".join(f"- {p.name}" for p in [args.tax_return, *args.source_documents])
    report_path.write_text(
        f"# Tax return double-check\n\nModel: {MODEL} (local)  \nFiles reviewed:\n{reviewed}\n\n{answer}\n\n"
        f"<details><summary>Model reasoning and calculations</summary>\n\n{work_log}\n\n</details>\n"
    )
    print(f"\nSaved report: {report_path}")

    while sys.stdin.isatty():
        try:
            question = input("\nAsk a follow-up question (or press Enter to finish): ").strip()
        except EOFError:
            break
        if not question:
            break
        messages.append({"role": "user", "content": question})
        _, answer = get_reply(messages)
        with report_path.open("a") as report_file:
            report_file.write(f"\n## Follow-up: {question}\n\n{answer}\n")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        sys.exit("\nStopped.")
