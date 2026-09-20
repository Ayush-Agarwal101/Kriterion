from pathlib import Path

path = Path("kriterion/adapters.py")
text = path.read_text(encoding="utf-8")

old = "Fixture response: workload-specific request handled."
new = "Fixture response: workload-specific request handled with evidence, tasks, and source citation."

if old not in text:
    raise SystemExit(
        "Expected fixture response string was not found in kriterion/adapters.py; "
        "inspect the adapter before changing it."
    )

if new not in text:
    text = text.replace(old, new)

path.write_text(text, encoding="utf-8")
print("Updated LocalFixtureAdapter document-task response.")
