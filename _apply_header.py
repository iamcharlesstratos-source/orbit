# One-shot: replace the sidebar logo block with the compact horizontal brand header
# that matches the approved Open Nav mockup (icon box + serif Orbit + subtitle).
p = "app.py"
src = open(p, encoding="utf-8").read()

start = '    _logo_path = ROOT / "static" / "orbit_logo.png"'
end = "    # ---- Premium nav"
i = src.find(start)
j = src.find(end)
assert i != -1 and j != -1 and j > i, (i, j)

# include the preceding "# ---- Orbit logo" comment if right above
pre = "    # ---- Orbit logo"
ip = src.rfind(pre, 0, i)
if ip != -1 and ip > i - 160:
    i = ip

new = (
    "    # ---- Orbit brand header (compact horizontal — matches Open Nav mockup) ----\n"
    "    st.markdown(\n"
    "        \"<div style='display:flex;align-items:center;gap:11px;padding:4px 6px 0 6px'>\"\n"
    "        \"<div style='width:38px;height:38px;border-radius:11px;flex-shrink:0;display:grid;\"\n"
    "        \"place-items:center;background:linear-gradient(135deg,rgba(212,175,55,0.28),rgba(212,175,55,0.06));\"\n"
    "        \"border:1px solid rgba(212,175,55,0.40);color:var(--pra-accent);font-size:1.15rem'>◐</div>\"\n"
    "        \"<div style='line-height:1.05'>\"\n"
    "        \"<div style='font-family:Fraunces,Georgia,serif;font-size:1.35rem;font-weight:700;\"\n"
    "        \"color:var(--pra-text-strong)'>Orbit</div>\"\n"
    "        \"<div style='font-size:0.58rem;letter-spacing:0.16em;text-transform:uppercase;\"\n"
    "        \"color:var(--pra-text-dim);margin-top:1px'>Research Hunter</div>\"\n"
    "        \"</div></div>\",\n"
    "        unsafe_allow_html=True,\n"
    "    )\n"
    "    st.markdown(\n"
    "        \"<div style='height:1px;background:var(--pra-border);margin:9px 4px 2px'></div>\",\n"
    "        unsafe_allow_html=True,\n"
    "    )\n\n"
)

src = src[:i] + new + src[j:]
open(p, "w", encoding="utf-8").write(src)
print("header replaced")

import py_compile
py_compile.compile(p, doraise=True)
print("compile OK")
