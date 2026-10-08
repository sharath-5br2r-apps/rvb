# 1 — Custom Keystore Handling (Downstream Fork)

**Status:** accepted (2026-10-08)  
**Affects:** `scripts/utils.sh`, `scripts/build.sh`, `.github/workflows/build.yml`, `.github/workflows/ci.yml`, `docs/local-build.md`

## Context

Upstream `nullcpy/rvb` introduced dual-keystore identity requirements ([0008](../0008-signing-identity-is-secret-only.md)) utilizing an external helper script `.github/scripts/install_keystore.sh` and four secrets (`KEYSTORE_B64`, `KEYSTORE_P12_B64`, `KEYSTORE_PASSWORD`, `KEY_ALIAS`), expecting separate files for BKS and PKCS12 keystore formats.

In this downstream fork (`sharath-5br2r-apps/revanced-morphe-xposed-builder`), builds run both in GitHub Actions and locally in environments like Android (Termux) and Linux without requiring duplicate keystore files or external setup scripts. Furthermore, `install_keystore.sh` was completely removed, integrating all keystore resolution directly into `scripts/utils.sh`.

Additionally, in this fork, apksigner specifically requires BKS format for APK signing (`sign_apk` and `merge_splits`), handled through Bouncy Castle provider (`org.bouncycastle.jce.provider.BouncyCastleProvider` via `get_bcprov` and `bcprov.jar`).

## Decision

1. **Universal Single-Keystore Configuration**:
   - Instead of repo-prefixed `RVB_*` variables or dual stores (`KEYSTORE_B64` + `KEYSTORE_P12_B64`), the fork uses universal, all-caps environment variables:
     - `KEYSTORE` (or `KEYSTORE_FILE`)
     - `KEYSTORE_BASE64`
     - `KEYSTORE_PASSWORD`
     - `KEYSTORE_KEY_PASSWORD` (defaults to `KEYSTORE_PASSWORD` if unset)
     - `KEYSTORE_ALIAS`
   - Local setups can declare these in a local `.env` file, which `scripts/utils.sh` automatically detects and sources if present.

2. **Mandatory BKS Keystore & Runtime Dynamic Conversion**:
   - The primary signing identity is a single BKS keystore (`KEYSTORE` / `RVB_KEYSTORE`).
   - Apksigner invocations in `scripts/utils.sh` (`sign_apk` and `merge_splits`) explicitly sign using:
     ```bash
     java -cp "$APKSIGNER$javapathsep$TEMP_DIR/bcprov.jar" com.android.apksigner.ApkSignerTool sign \
         --ks "$RVB_KEYSTORE" \
         --ks-provider-class org.bouncycastle.jce.provider.BouncyCastleProvider \
         --ks-type BKS \
         --ks-pass "pass:$RVB_KEYSTORE_PASS" \
         --key-pass "pass:$key_pass" \
         --ks-key-alias "$RVB_KEY_ALIAS" ...
     ```
   - For tools that strictly require a PKCS12 store (e.g., LSPatch), `scripts/utils.sh` provides the `require_p12()` helper function. It dynamically inspects the BKS keystore using `keytool` and converts it to PKCS12 (`TEMP_DIR/ks-p12.keystore`) on-the-fly using Bouncy Castle (`get_bcprov`).

3. **Special Character Escaping for `eval`**:
   - Instead of restricting passwords and aliases to strictly alphanumeric characters, keystore variables (`KEYSTORE_PASSWORD`, `KEYSTORE_KEY_PASSWORD`, `KEYSTORE_ALIAS`, and keystore paths) have `$`, `` ` ``, `\`, and `"` escaped using `_escape_eval_arg` specifically where command strings are evaluated via `eval`.
   - Direct command invocations (such as `apksigner` and `keytool`) receive the unescaped raw values.

4. **Integrated in `scripts/utils.sh` (No `install_keystore.sh` or External `needs-bks` Checks)**:
   - The standalone `.github/scripts/install_keystore.sh` script and external `needs-bks` checks are removed as obsolete.
   - All tools except Morphe require the Bouncy Castle provider (`bcprov.jar`) for BKS keystore access (NPatch, ReVanced CLI, apksigner, and keytool BKS conversions). Morphe bundles its own BC provider.
   - Provider availability is managed on-demand via `get_bcprov` directly inside `scripts/utils.sh`.
   - Keystore decoding (if base64), path checks, parameter normalization, and identity verification (`require_signing_identity`) are executed directly inside `scripts/utils.sh` and checked before any downloads in `scripts/build.sh`.

## Verification

- `scripts/utils.sh` loads variables cleanly from environment or `.env` and rejects missing identities via `require_signing_identity`.
- Apksigner signs successfully with BKS format using `TEMP_DIR/bcprov.jar`.
- Any tool requesting PKCS12 triggers `require_p12()` which converts the BKS keystore dynamically.
