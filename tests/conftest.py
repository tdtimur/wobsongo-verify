import os

# Low bcrypt cost for tests — keeps the suite fast without disabling hashing.
# Must be set before any import that calls hash_password().
os.environ.setdefault("WOBSONGO_BCRYPT_ROUNDS", "4")
