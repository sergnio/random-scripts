# Tax return check

`tax_check.py` double-checks a 2025 federal tax return (Form 1040) that an accountant or tax software prepared. A model running on your own computer compares the return against your W-2s and 1099s and looks for mistakes. **Nothing is sent over the internet.**

It's a second opinion, not tax advice. Treat what it flags as questions for your preparer.

## What it checks

- Every W-2, 1099, and 1098 amount lands on the right line of the return.
- The math on every add and subtract line.
- The 2025 standard deduction, the new Schedule 1-A deductions (tips, overtime, car loan interest, seniors), and credits.
- The line 16 tax. This comes from code that matches every row of the IRS Tax Table, not from the model's own math.
- Deductions or credits your documents suggest you may have missed.

## Requirements

- Python 3.9 or newer. No Python packages are required.
- `pdftotext` from poppler (on a Mac with Homebrew: `brew install poppler`)
- `llama-server` from llama.cpp (`brew install llama.cpp`)
- About 24 GB of free memory for the model. Tested on an Apple Silicon Mac with 36 GB.

## Set up the model (once)

The model is Qwen3.6 35B-A3B, picked with [llmfit](https://github.com/AlexsJones/llmfit) as the strongest model that fits a 36 GB Mac. Download it (20.6 GB) and start the server:

```bash
llmfit download unsloth/Qwen3.6-35B-A3B-GGUF --quant Q4_K_M

llama-server \
  -m ~/.cache/llmfit/models/Qwen3.6-35B-A3B-UD-Q4_K_M.gguf \
  --alias qwen3.6:35b-a3b --ctx-size 65536 --port 11434
```

Leave the server running while you check a return. To use a different address or model, change `SERVER` and `MODEL` at the top of `tax_check.py`.

## Check a return

```bash
python3 tax-check/tax_check.py \
  "$HOME/Documents/Taxes/2025/return.pdf" \
  "$HOME/Documents/Taxes/2025/w2.pdf" \
  "$HOME/Documents/Taxes/2025/1099-int.pdf"
```

- The first file is the prepared return. List every W-2, 1099, and 1098 after it. Without them, it can only check the math and the 2025 rules.
- Use the PDF the tax software produced. Scans and photos have no readable text; a `.txt` file with the numbers typed in also works.
- A review takes about 2 minutes on the tested Mac. The first run also takes about a minute to load the model.

The report prints in the terminal and is saved next to the return as `return-review-YYYY-MM-DD-HHMM.md`. It has a verdict, likely errors with the math shown, items worth asking about, possibly missed savings, a checklist, and questions you can send your preparer as-is. Afterward you can ask follow-up questions, and the answers are added to the report.

To run it as `tax-check` from anywhere:

```bash
ln -s "$PWD/tax-check/tax_check.py" ~/.local/bin/tax-check
```

## Privacy

- Everything runs on your computer. The script only talks to `llama-server` on `127.0.0.1`.
- SSNs and bank account numbers are masked to their last 4 digits before the model reads anything.
- Reports contain your tax details. They're saved next to your return, outside this repository. Don't copy them in here.

## Limits

- Federal Form 1040 for tax year 2025 only. State returns aren't checked.
- The model reads about 25 to 30 dense form pages at once. If a PDF is too long, the script says so: remove cover letters, state returns, and e-file pages and try again. Starting the server with `--ctx-size 131072` doubles that for about 1.3 GB more memory.
- The tax calculation doesn't cover the Schedule D Tax Worksheet (collectibles or unrecaptured section 1250 gain), the kiddie tax (Form 8615), or the foreign earned income exclusion.
- The model can still miss things or be wrong.

## Updating for a new tax year

- `reviewer-prompt.md` has the reference figures and the Form 1040 line map.
- `tax_2025.py` has the brackets and capital gain thresholds. Copy it to the new year and update the import and tool name in `tax_check.py` and `reviewer-prompt.md`.
- Check every figure against the IRS: the Form 1040 instructions, the yearly inflation adjustment revenue procedure, and the Tax Table (`i1040tt.pdf`).
