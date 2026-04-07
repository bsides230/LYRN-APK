import os
import sys

# Add root dir to path to import automation_controller
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from automation_controller import AutomationController

def execute_sequence(sequence_string):
    if not sequence_string:
        return

    steps = [s.strip() for s in sequence_string.split(";") if s.strip()]
    if not steps:
        return

    ac = AutomationController()

    for step in steps:
        if step.startswith("script:"):
            name = step.split(":", 1)[1]
            ac.add_job(name=name)
        elif step.startswith("job:"):
            name = step.split(":", 1)[1]
            ac.add_job(name=name)
        elif step.startswith("affordance:"):
            name = step.split(":", 1)[1]
            # Enqueue the affordance so the scheduler handles it in order
            ac.add_job(name=f"affordance:{name}")

if __name__ == "__main__":
    if len(sys.argv) > 1:
        execute_sequence(sys.argv[1])
