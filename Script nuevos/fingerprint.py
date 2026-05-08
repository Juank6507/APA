import sys
import json

def fingerprint(path):
    with open(path, 'r', encoding='utf-8') as f:
        content = f.read()
    lines = content.splitlines()
    return {
        "lines": len(lines),
        "chars": len(content),
        "ascii_sum_mod": sum(ord(c) for c in content) % 100000,
        "first_three": "\n".join(lines[:3]),
        "last_three": "\n".join(lines[-3:])
    }

if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("Uso: python fingerprint.py <archivo>")
        sys.exit(1)
    print(json.dumps(fingerprint(sys.argv[1]), indent=2, ensure_ascii=False))