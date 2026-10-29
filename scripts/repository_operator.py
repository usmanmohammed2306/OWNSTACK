"""Run queued local Cockpit repository checks without model usage."""
from ownstack.repository_supervisor import main

if __name__ == '__main__':
    raise SystemExit(main())
