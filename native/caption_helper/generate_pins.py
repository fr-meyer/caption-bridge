import pathlib, re, subprocess, sys
root = pathlib.Path(sys.argv[1])
names = ("GuardianA", "GuardianB", "SyntheticHelper")
hashes = []
for name in names:
    result = subprocess.run(["/usr/bin/codesign", "-dv", "--verbose=4", str(root/name)], capture_output=True, text=True, check=True)
    match = re.search(r"^CDHash=([0-9a-f]{40,64})$", result.stderr, re.M)
    if not match:
        raise SystemExit("missing code hash")
    hashes.append(match[1])
quote = chr(34)
lines = ["static const char *cb_role_identifiers[]={" + ",".join(quote+"local.captionbridge."+n+quote for n in names) + "};", "static const char *cb_role_hashes[]={" + ",".join(quote+h+quote for h in hashes) + "};"]
pathlib.Path(sys.argv[2]).write_text(chr(10).join(lines)+chr(10))
