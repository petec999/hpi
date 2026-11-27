#!/usr/bin/env python3
"""Protect local privileged routes and socket handlers using existing Flask login."""
import ast
import re

MARK="# HPI LOCAL AUTH v1"
HELPER='''# HPI LOCAL AUTH v1
def _hpi_web_secret():
    import secrets
    import stat
    path="/opt/haier/.hpi-web-secret-v1"

    def read_secret():
        # Reject symlinks, non-regular files and group/world-accessible keys.
        fd=os.open(path,os.O_RDONLY|os.O_NOFOLLOW|os.O_NONBLOCK)
        with os.fdopen(fd,"rb") as stream:
            st=os.fstat(stream.fileno())
            if not stat.S_ISREG(st.st_mode) or st.st_mode & 0o077:
                raise ValueError("Invalid local web secret permissions")
            raw=stream.read(65)
        if len(raw)!=64 or any(c not in b"0123456789abcdef" for c in raw):
            raise ValueError("Invalid local web secret")
        return raw.decode("ascii")

    try:
        return read_secret()
    except FileNotFoundError:
        pass
    fd,tmp=tempfile.mkstemp(prefix=".hpi-web-key-",dir=os.path.dirname(path))
    try:
        with os.fdopen(fd,"wb") as stream:
            stream.write(secrets.token_hex(32).encode("ascii"))
            stream.flush()
            os.fsync(stream.fileno())
        try:
            os.link(tmp,path)
        except FileExistsError:
            pass
        dirfd=os.open(os.path.dirname(path),os.O_RDONLY|os.O_DIRECTORY)
        try:
            os.fsync(dirfd)
        finally:
            os.close(dirfd)
        return read_secret()
    finally:
        os.unlink(tmp)

'''

def patch(source):
    if MARK in source:
        if HELPER not in source:
            raise ValueError("Modified local auth guard")
        return source
    tree=ast.parse(source)
    matches=[n for n in tree.body if isinstance(n,ast.Assign) and len(n.targets)==1
             and isinstance(n.targets[0],ast.Subscript)
             and ast.unparse(n.targets[0].value)=="app.config"
             and isinstance(n.targets[0].slice,ast.Constant) and n.targets[0].slice.value=="SECRET_KEY"]
    if len(matches)!=1 or not isinstance(matches[0].value,ast.Constant) or not isinstance(matches[0].value.value,str):
        raise ValueError("Unexpected Flask secret assignment")
    n=matches[0]
    lines=source.splitlines(keepends=True)
    lines[n.lineno-1:n.end_lineno]=[HELPER+'app.config["SECRET_KEY"] = _hpi_web_secret()\n']
    source="".join(lines)
    for name in ("theme_route","backup_route","upload_file"):
        tree=ast.parse(source)
        nodes=[n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name==name]
        if len(nodes)!=1 or not any(isinstance(d,ast.Call) and ast.unparse(d.func)=="app.route" for d in nodes[0].decorator_list):
            raise ValueError("Unexpected route: "+name)
        n=nodes[0]
        if any(isinstance(d,ast.Name) and d.id=="login_required" for d in n.decorator_list):
            continue
        lines=source.splitlines(keepends=True)
        lines.insert(n.lineno-1,"@login_required\n")
        source="".join(lines)
    for name,guard in (("handle_connect","    if not is_logged_in():\n        return False\n"),
                       ("handle_client_message","    if not is_logged_in() or not isinstance(data,dict):\n        return\n")):
        tree=ast.parse(source)
        nodes=[n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name==name]
        if len(nodes)!=1 or not any(isinstance(d,ast.Call) and ast.unparse(d.func)=="socketlocal.on" for d in nodes[0].decorator_list):
            raise ValueError("Unexpected socket handler: "+name)
        n=nodes[0]
        lines=source.splitlines(keepends=True)
        # Keep global declarations first; never log raw settings payloads.
        i=0
        while i<len(n.body) and isinstance(n.body[i],ast.Global):
            i+=1
        lines.insert(n.body[i].lineno-1,guard)
        source="".join(lines)
    tree=ast.parse(source)
    n=next(n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name=="handle_client_message")
    lines=source.splitlines(keepends=True)
    for call in ast.walk(n):
        if isinstance(call,ast.Expr) and isinstance(call.value,ast.Call) and ast.unparse(call.value.func)=="logging.debug" and len(call.value.args)==1 and isinstance(call.value.args[0],ast.Name) and call.value.args[0].id=="data":
            lines[call.lineno-1]=" "*call.col_offset+"logging.debug('Local authenticated socket request')\n"
    source="".join(lines)
    compile(source,"main.py","exec")
    return source
