"""Командная строка: сгенерировать пакет задания и напечатать JSON.

    python -m astrosim rv-binary --seed 7            # только public
    python -m astrosim rv-binary --seed 7 --private  # с истиной, ключом и решением
    python -m astrosim rv-binary --seed 7 --grade k_a=26 k_b=27 ...
"""
from __future__ import annotations

import argparse
import json
import sys

from astrosim.tasks.registry import FAMILIES


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="astrosim")
    parser.add_argument("family", choices=sorted(FAMILIES))
    parser.add_argument("--seed", type=int, required=True)
    parser.add_argument("--private", action="store_true", help="включить истину, ключ и решение")
    parser.add_argument("--grade", nargs="*", metavar="FIELD=ANSWER", help="проверить ответы")
    args = parser.parse_args(argv)
    module = FAMILIES[args.family]
    package = module.generate(args.seed)
    if args.grade is not None:
        answers = dict(item.split("=", 1) for item in args.grade)
        print(json.dumps(module.grade(package, answers).to_dict(), ensure_ascii=False, indent=2))
        return 0
    print(json.dumps(package.to_dict(include_private=args.private), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
