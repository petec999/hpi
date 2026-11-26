"""AST report of control output call sites in extracted HaierPi source.

This is a static inventory, not proof of exclusive runtime ownership.
No source imports, execution or edits.
"""
import ast
import argparse
from pathlib import Path

NAMES={"new_presetchange","flimitchange","gpiocontrol","set_newframe","new_tempchange",
       "WritePump","SetMode","output","setup"}

class Inventory(ast.NodeVisitor):
    def __init__(self,source):
        self.source=source
        self.scope=[]
        self.rows=[]
    def visit_FunctionDef(self,node):
        self.scope.append(node.name)
        self.generic_visit(node)
        self.scope.pop()
    visit_AsyncFunctionDef=visit_FunctionDef
    def visit_Call(self,node):
        f=node.func
        name=f.id if isinstance(f,ast.Name) else f.attr if isinstance(f,ast.Attribute) else None
        if name in NAMES:
            raw=ast.get_source_segment(self.source,node) or name
            raw=" ".join(raw.split())
            # Exclude unrelated generic calls on other receivers.
            if name not in {"output","setup"} or raw.startswith("GPIO."):
                self.rows.append((node.lineno,".".join(self.scope) or "<module>",raw[:220]))
        self.generic_visit(node)

def inventory(source):
    v=Inventory(source)
    v.visit(ast.parse(source))
    return v.rows

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("source",type=Path)
    a=p.parse_args()
    for line,scope,call in inventory(a.source.read_text(encoding="utf-8")):
        print(f"{line:5} {scope:40} {call}")

if __name__=="__main__":
    main()
