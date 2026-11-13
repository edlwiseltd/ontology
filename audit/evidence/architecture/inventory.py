import ast, sys, pathlib, collections
root = pathlib.Path(sys.argv[1])
mods = sorted(root.glob("*.py"))
names = {m.stem for m in mods}
graph = {}
for m in mods:
    src = m.read_text()
    t = ast.parse(src)
    doc = (ast.get_docstring(t) or "").strip().splitlines()
    imps = set(); lazy=set(); ext=set()
    for node in ast.walk(t):
        if isinstance(node, ast.ImportFrom):
            if node.level >= 1:
                if node.module:
                    tgt = node.module.split(".")[0]
                    (imps if node in t.body else lazy).add(tgt)
                else:
                    for a in node.names:
                        if a.name in names: (imps if node in t.body else lazy).add(a.name)
            else:
                ext.add(node.module.split(".")[0])
        elif isinstance(node, ast.Import):
            for a in node.names: ext.add(a.name.split(".")[0])
    # top-level-ness: check if in module body or inside try at module level
    top = set()
    for node in t.body:
        for sub in ast.walk(node):
            if isinstance(sub, ast.ImportFrom) and sub.level>=1:
                if not isinstance(node,(ast.FunctionDef,ast.ClassDef,ast.AsyncFunctionDef)):
                    if sub.module: top.add(sub.module.split(".")[0])
                    else: top.update(a.name for a in sub.names if a.name in names)
    alli=set()
    for sub in ast.walk(t):
        if isinstance(sub, ast.ImportFrom) and sub.level>=1:
            if sub.module: alli.add(sub.module.split(".")[0])
            else: alli.update(a.name for a in sub.names if a.name in names)
    lazy = alli-top
    pub_cls=[n.name for n in t.body if isinstance(n,ast.ClassDef) and not n.name.startswith("_")]
    pub_fn=[n.name for n in t.body if isinstance(n,(ast.FunctionDef,ast.AsyncFunctionDef)) and not n.name.startswith("_")]
    graph[m.stem]=(sorted(top),sorted(lazy))
    std = sorted(e for e in ext if e not in names)
    print(f"## {m.stem} ({len(src.splitlines())} lines)\n  doc: {doc[0] if doc else '-'}\n  classes: {pub_cls}\n  funcs: {pub_fn}\n  imports(top): {sorted(top)}\n  imports(lazy): {sorted(lazy)}\n  external: {std}")
print("\n# fan-in")
fanin=collections.Counter()
for k,(a,b) in graph.items():
    for x in set(a)|set(b): fanin[x]+=1
for k in sorted(graph, key=lambda k:-fanin[k]): print(k, "fan-in", fanin[k], "fan-out", len(set(graph[k][0])|set(graph[k][1])))
# cycles (top-level only and all)
def cycles(edges):
    import itertools
    idx={};low={};st=[];on=set();res=[];c=[0]
    def sc(v):
        idx[v]=low[v]=c[0];c[0]+=1;st.append(v);on.add(v)
        for w in edges.get(v,[]):
            if w not in edges: continue
            if w not in idx: sc(w);low[v]=min(low[v],low[w])
            elif w in on: low[v]=min(low[v],idx[w])
        if low[v]==idx[v]:
            comp=[]
            while True:
                w=st.pop();on.discard(w);comp.append(w)
                if w==v:break
            if len(comp)>1:res.append(sorted(comp))
    sys.setrecursionlimit(10000)
    for v in edges:
        if v not in idx: sc(v)
    return res
print("\n# SCCs top-level:", cycles({k:v[0] for k,v in graph.items()}))
print("# SCCs incl lazy:", cycles({k:v[0]+v[1] for k,v in graph.items()}))
