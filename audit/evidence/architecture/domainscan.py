import ast, sys, re, pathlib
words = re.compile(r"\b(claim(?!s?_?(?:set|name)?\b(?=.*oidc))|insur\w*|customer\w*|onboard\w*|contract\w*|patient\w*|referral\w*|kyc\w*|invoice\w*|vehicle\w*|policyholder\w*|machine\w*|shipment\w*|fulfil\w*|sku\w*|warehouse_order|order_\w+|orders?\b|it-integration|compliance-officer|underwriter\w*|adjuster\w*)", re.I)
for p in sorted(pathlib.Path(sys.argv[1]).glob("*.py")):
    t = ast.parse(p.read_text())
    docs = set()
    for n in ast.walk(t):
        if isinstance(n,(ast.Module,ast.FunctionDef,ast.ClassDef,ast.AsyncFunctionDef)) and n.body and isinstance(n.body[0],ast.Expr) and isinstance(getattr(n.body[0],'value',None),ast.Constant) and isinstance(n.body[0].value.value,str):
            docs.add(id(n.body[0].value))
    for n in ast.walk(t):
        if isinstance(n, ast.Constant) and isinstance(n.value,str) and id(n) not in docs:
            for m in words.finditer(n.value):
                print(f"{p.name}:{n.lineno}: str {m.group(0)!r}: {n.value[:90]!r}")
        elif isinstance(n, ast.Name) or isinstance(n, ast.Attribute) or isinstance(n, ast.arg) or isinstance(n,(ast.FunctionDef,ast.ClassDef)):
            name = getattr(n,'id',None) or getattr(n,'attr',None) or getattr(n,'arg',None) or getattr(n,'name',None)
            if name and words.search(name): print(f"{p.name}:{n.lineno}: ident {name}")
