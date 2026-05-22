#!/bin/sh
set -u

fail()
{
    echo "PATCH_TEST_FAILED: $*"
    exit 1
}

expect_status()
{
    expected="$1"
    shift

    "$@"
    status=$?
    if [ "$status" -ne "$expected" ]; then
        fail "$* exited $status, expected $expected"
    fi
}

echo "=== GNU patch app test ==="

apk update || fail "apk update"
apk add patch diffutils || fail "apk add patch diffutils"

command -v patch >/dev/null 2>&1 || fail "patch is missing"
patch --version | head -n 1 | grep -q "GNU patch" || fail "not GNU patch"

workdir="/tmp/starry-patch"
rm -rf "$workdir"
mkdir -p "$workdir" || fail "mkdir workdir"
cd "$workdir" || fail "cd workdir"

cat > file.txt <<'EOF' || fail "write file.txt"
alpha
beta
omega
EOF

cat > change.patch <<'EOF' || fail "write change.patch"
--- file.txt
+++ file.txt
@@ -1,3 +1,3 @@
 alpha
-beta
+gamma
 omega
EOF

expect_status 0 patch -p0 -i change.patch
grep -q "^gamma$" file.txt || fail "basic patch did not update file"

expect_status 0 patch --dry-run -R -p0 -i change.patch
grep -q "^gamma$" file.txt || fail "dry-run modified file"

expect_status 0 patch -R -p0 -i change.patch
grep -q "^beta$" file.txt || fail "reverse patch did not restore file"

cat > create.patch <<'EOF' || fail "write create.patch"
--- /dev/null
+++ created.txt
@@ -0,0 +1,2 @@
+created
+line
EOF

expect_status 0 patch -p0 -i create.patch
grep -q "^created$" created.txt || fail "create-file patch missing content"
grep -q "^line$" created.txt || fail "create-file patch incomplete"

cat > delete-me.txt <<'EOF' || fail "write delete-me.txt"
remove
me
EOF

cat > delete.patch <<'EOF' || fail "write delete.patch"
--- delete-me.txt
+++ /dev/null
@@ -1,2 +0,0 @@
-remove
-me
EOF

expect_status 0 patch -p0 -i delete.patch
test ! -e delete-me.txt || fail "delete-file patch left file behind"

mkdir -p pkg || fail "mkdir pkg"
cat > pkg/config.txt <<'EOF' || fail "write pkg/config.txt"
name=old
mode=test
EOF

cat > strip.patch <<'EOF' || fail "write strip.patch"
--- a/pkg/config.txt
+++ b/pkg/config.txt
@@ -1,2 +1,2 @@
-name=old
+name=new
 mode=test
EOF

expect_status 0 patch -p1 -i strip.patch
grep -q "^name=new$" pkg/config.txt || fail "patch -p1 did not update nested path"

cat > generated.patch <<'EOF' || fail "write generated.patch"
--- generated.txt
+++ generated.txt
@@ -1,2 +1,2 @@
 before
-left
+right
EOF
cat > generated.txt <<'EOF' || fail "write generated.txt"
before
left
EOF
cp generated.txt generated.orig || fail "copy generated.orig"
patch -p0 -i generated.patch >/dev/null || fail "apply generated.patch"
diff -u generated.orig generated.txt > generated.diff
status=$?
if [ "$status" -ne 1 ]; then
    fail "diff of patched file exited $status, expected 1"
fi
grep -q "^+right$" generated.diff || fail "patched diff missing added line"

cat > reject.txt <<'EOF' || fail "write reject.txt"
actual
content
EOF

cat > reject.patch <<'EOF' || fail "write reject.patch"
--- reject.txt
+++ reject.txt
@@ -1,2 +1,2 @@
-expected
+changed
 content
EOF

patch -p0 -i reject.patch > reject.out 2> reject.err
status=$?
if [ "$status" -eq 0 ]; then
    fail "reject patch unexpectedly succeeded"
fi
test -s reject.txt.rej || fail "reject patch did not create .rej file"
grep -q "^actual$" reject.txt || fail "reject patch corrupted original file"

rm -rf "$workdir" || fail "cleanup"

echo "PATCH_TEST_PASSED"
