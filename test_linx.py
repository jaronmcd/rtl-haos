import subprocess
import json
import sys

# Standard command line without the 'match' filter
RTL_COMMAND = [
    "rtl_433",
    "-f", "418M",
    "-R", "0",
    "-X", "n=Linx,m=OOK_PWM,s=460,l=890,r=5000",
    "-F", "json"
]

# STRICTER KEYS: We added "00" to the front of every ID.
# This ensures we don't accidentally match random noise.
BUTTON_MAP = {
    "0055558": "Button 1",
    "0055570": "Button 2",
    "00555d0": "Button 3",
    "0055750": "Button 4",
    "0055d50": "Button 5",
    "0057550": "Button 6",
    "005d550": "Button 7",
    "0075550": "Button 8"
}

# MINIMUM LENGTH: Ignores short noise fragments (like "a800")
MIN_LENGTH = 10

def main():
    print("------------------------------------------------")
    print("🔒 STARTING STRICT DECODER")
    print("   Filtering noise (Len < 10) and verifying prefixes...")
    print("------------------------------------------------")

    try:
        process = subprocess.Popen(
            RTL_COMMAND,
            stdout=subprocess.PIPE,
            stderr=sys.stderr,
            text=True
        )

        for line in process.stdout:
            try:
                data = json.loads(line)

                if "rows" in data:
                    for row in data["rows"]:
                        if "data" in row:
                            raw_hex = row["data"]

                            # RULE 1: Length Check
                            if len(raw_hex) < MIN_LENGTH:
                                continue # Skip this row silently

                            # RULE 2: Check Stricter Suffix
                            match_found = False
                            for suffix, btn_name in BUTTON_MAP.items():
                                if raw_hex.endswith(suffix):
                                    print(f"🎉 VALID BUTTON: {btn_name}")
                                    print(f"   (Code: {raw_hex})")
                                    match_found = True
                                    break

                            # Optional: Uncomment to see what "Long" noise looks like
                            # if not match_found:
                            #     print(f"   [Ignored Noise]: {raw_hex}")

            except json.JSONDecodeError:
                pass

    except KeyboardInterrupt:
        print("\n🛑 Stopping.")
        process.terminate()
        sys.exit(0)

if __name__ == "__main__":
    main()
