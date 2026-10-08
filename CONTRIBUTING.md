# Contributing

Thanks for your interest in **ZCode Claim · 9Router Pipeline**.

## Ground rules

- Only work with **accounts you own**. Anything that reads, stores, or transmits
  third-party credentials will be rejected.
- Keep the toolkit **dependency-light** — prefer the standard library; only add a
  package when there is no reasonable alternative.
- Never commit secrets: tokens, cookies, JWTs, API keys, or `.env` files.
  `examples/*.example.*` show the required shape with dummy values.

## Getting set up

```bash
pip install websockets playwright
python src/zcode_claim.py --help
```

## Making a change

1. Fork the repo and create a branch: `git checkout -b feat/short-name`.
2. Keep changes focused; one logical change per pull request.
3. Match the existing style (PEP 8, small functions, no dead code).
4. If you touch a stage, update the relevant README paragraph and, where the
   flow changes, `docs/STRUCTURE.md`.
5. Run a quick syntax check before pushing:

   ```bash
   python -m py_compile src/*.py
   ```

6. Open a pull request describing **what** changed, **why**, and **how you
   tested it** (which stage, which browser/endpoint).

## Reporting bugs

Open an issue with: the stage, the exact command, the observed output, and the
expected output. **Redact all tokens, cookies, and keys.**

## Scope

This project automates an undisclosed API. Upstream changes can break any stage
at any time; fixes that adapt to a changed upstream are welcome, but please cite
the evidence (request/response, app version) in the PR.
