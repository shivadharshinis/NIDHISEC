"""NidhiSec management commands.

Run from the `backend` folder with the virtual environment active:

    python -m app.cli init-env            # create .env with a fresh JWT secret
    python -m app.cli seed-demo           # development only: fictional demo data
    python -m app.cli seed-demo --reset-passwords
    python -m app.cli create-institution --code ABC-123 --name "..."
    python -m app.cli create-user --email ... --name ... --role AICTE_OFFICIAL
    python -m app.cli lifecycle-check     # maturity alerts; safe to run repeatedly (e.g. daily)
"""

import argparse
import getpass
import secrets
import sys
from datetime import date, timedelta
from decimal import Decimal

from sqlalchemy import inspect, select

from app.core.config import BACKEND_DIR, get_settings

ENV_FILE = BACKEND_DIR / ".env"
ENV_EXAMPLE = BACKEND_DIR / ".env.example"
CREDENTIALS_FILE = BACKEND_DIR / "data" / "dev-credentials.txt"
MIN_PASSWORD_LENGTH = 12


def generate_password() -> str:
    return secrets.token_urlsafe(12)  # 16 characters, ~96 bits of entropy


# ---------- init-env ----------


def cmd_init_env(_args: argparse.Namespace) -> int:
    secret = secrets.token_urlsafe(48)
    if not ENV_FILE.exists():
        lines = ENV_EXAMPLE.read_text(encoding="utf-8").splitlines()
        lines = [f"NIDHISEC_JWT_SECRET={secret}" if line.startswith("NIDHISEC_JWT_SECRET=") else line for line in lines]
        ENV_FILE.write_text("\n".join(lines) + "\n", encoding="utf-8")
        print(f"Created {ENV_FILE} with a new JWT secret.")
        return 0

    lines = ENV_FILE.read_text(encoding="utf-8").splitlines()
    existing = [line for line in lines if line.startswith("NIDHISEC_JWT_SECRET=")]
    if existing and existing[0].split("=", 1)[1].strip():
        print(f"{ENV_FILE} already has a JWT secret; nothing changed.")
        return 0
    if existing:
        lines = [f"NIDHISEC_JWT_SECRET={secret}" if line.startswith("NIDHISEC_JWT_SECRET=") else line for line in lines]
    else:
        lines.append(f"NIDHISEC_JWT_SECRET={secret}")
    ENV_FILE.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"Added a new JWT secret to {ENV_FILE}.")
    return 0


# ---------- database helpers ----------


def _open_session():
    from app.db.session import SessionLocal, engine

    if not inspect(engine).has_table("alembic_version"):
        print("Database schema is not initialised. Run `alembic upgrade head` first.", file=sys.stderr)
        raise SystemExit(1)
    return SessionLocal()


# ---------- seed-demo ----------

# Entirely fictional. Email domains use the reserved example.org domain.
DEMO_INSTITUTIONS = [
    {
        "code": "DEMO-INST-001",
        "name": "Demo Institute of Technology, Northfield",
        "contact_email": "office@demo-institute.example.org",
        "state": "Demo State",
    },
    {
        "code": "DEMO-INST-002",
        "name": "Sample College of Engineering, Riverside",
        "contact_email": "office@sample-college.example.org",
        "state": "Demo State",
    },
]

DEMO_USERS = [
    ("institution1@demo-institute.example.org", "Asha Demo (Institution Admin)", "INSTITUTION", "DEMO-INST-001"),
    ("institution2@sample-college.example.org", "Ravi Sample (Institution Admin)", "INSTITUTION", "DEMO-INST-002"),
    ("bank.officer@demo-bank.example.org", "Meera Demo (Bank Officer)", "BANK_OFFICER", None),
    ("bank.officer2@demo-bank.example.org", "Vikram Demo (Bank Officer)", "BANK_OFFICER", None),
    ("aicte.official@aicte-demo.example.org", "Kiran Demo (AICTE Official)", "AICTE_OFFICIAL", None),
]


def _demo_fdrs(today: date) -> list[dict]:
    # The last entry deliberately reuses the reference of the first one at a
    # different institution, to demonstrate possible-duplicate flagging.
    return [
        dict(inst="DEMO-INST-001", bank="Demo National Bank", branch="Northfield Main", ifsc="DEMO0000101",
             number="DNB/FD/000123", amount="500000.00", issue=today - timedelta(days=400), tenure=1095),
        dict(inst="DEMO-INST-001", bank="Demo National Bank", branch="Northfield Main", ifsc="DEMO0000101",
             number="DNB/FD/000456", amount="250000.00", issue=today - timedelta(days=330), tenure=395),
        dict(inst="DEMO-INST-002", bank="Sample Co-operative Bank Ltd.", branch="Riverside", ifsc=None,
             number="SCB-77812", amount="750000.00", issue=today - timedelta(days=200), tenure=730),
        dict(inst="DEMO-INST-002", bank="Demo National Bank Ltd", branch="Riverside", ifsc="DEMO0000202",
             number="dnb-fd-000123", amount="500000.00", issue=today - timedelta(days=100), tenure=1095),
    ]


def cmd_seed_demo(args: argparse.Namespace) -> int:
    settings = get_settings()
    if not settings.is_development:
        print("seed-demo only runs when NIDHISEC_ENVIRONMENT=development.", file=sys.stderr)
        return 1

    from app.core.security import hash_password
    from app.models import FDR, AuditLog, FDRStatus, Institution, User, UserRole
    from app.services.fdrs import find_duplicates, to_paise
    from app.services.normalization import normalize_bank_name, normalize_fdr_number

    db = _open_session()
    credentials: list[tuple[str, str, str]] = []
    try:
        institutions: dict[str, Institution] = {}
        for data in DEMO_INSTITUTIONS:
            inst = db.scalars(select(Institution).where(Institution.code == data["code"])).one_or_none()
            if inst is None:
                inst = Institution(**data)
                db.add(inst)
            institutions[data["code"]] = inst
        db.flush()

        users: dict[str, User] = {}
        for email, name, role, inst_code in DEMO_USERS:
            user = db.scalars(select(User).where(User.email == email)).one_or_none()
            if user is None:
                password = generate_password()
                user = User(
                    email=email,
                    full_name=name,
                    role=UserRole(role),
                    institution_id=institutions[inst_code].id if inst_code else None,
                    password_hash=hash_password(password),
                    is_active=True,
                )
                db.add(user)
                credentials.append((role, email, password))
            elif args.reset_passwords:
                password = generate_password()
                user.password_hash = hash_password(password)
                credentials.append((role, email, password))
            users[email] = user
        db.flush()

        created_fdrs = 0
        if not args.no_fdrs and db.scalar(select(FDR.id).limit(1)) is None:
            inst_users = {u.institution_id: u for u in users.values() if u.institution_id}
            for spec in _demo_fdrs(date.today()):
                inst = institutions[spec["inst"]]
                author = inst_users[inst.id]
                fdr = FDR(
                    institution_id=inst.id,
                    bank_name=spec["bank"],
                    bank_name_normalized=normalize_bank_name(spec["bank"]),
                    branch_name=spec["branch"],
                    ifsc_code=spec["ifsc"],
                    fdr_number=spec["number"],
                    fdr_number_normalized=normalize_fdr_number(spec["number"]),
                    amount_paise=to_paise(Decimal(spec["amount"])),
                    issue_date=spec["issue"],
                    maturity_date=spec["issue"] + timedelta(days=spec["tenure"]),
                    remarks="Fictional demo record",
                    status=FDRStatus.SUBMITTED,
                    created_by_id=author.id,
                )
                db.add(fdr)
                db.flush()
                db.add(AuditLog(
                    actor_user_id=author.id, actor_email=author.email, actor_name=author.full_name,
                    actor_role=author.role.value, action="FDR_CREATED", entity_type="fdr", entity_id=fdr.id,
                    institution_id=inst.id, summary=f"FDR {fdr.fdr_number} ({fdr.bank_name}) submitted (demo seed)",
                ))
                matches = find_duplicates(db, fdr)
                if matches:
                    db.add(AuditLog(
                        actor_user_id=author.id, actor_email=author.email, actor_name=author.full_name,
                        actor_role=author.role.value, action="FDR_DUPLICATE_FLAGGED", entity_type="fdr",
                        entity_id=fdr.id, institution_id=inst.id, changes={"match_count": len(matches)},
                        summary=f"Possible duplicate of {len(matches)} existing record(s); flagged for review",
                    ))
                created_fdrs += 1
        db.commit()
    finally:
        db.close()

    print(f"Demo institutions: {len(DEMO_INSTITUTIONS)}  |  demo FDRs created: {created_fdrs}")
    if not credentials:
        print("Demo accounts already exist; passwords unchanged. Use --reset-passwords to generate new ones.")
        return 0

    # Merge with any existing file so accounts added later don't drop earlier entries.
    entries: dict[str, tuple[str, str]] = {}
    if CREDENTIALS_FILE.exists():
        for line in CREDENTIALS_FILE.read_text(encoding="utf-8").splitlines():
            parts = line.split()
            if len(parts) == 3 and "@" in parts[1]:
                entries[parts[1]] = (parts[0], parts[2])
    for role, email, password in credentials:
        entries[email] = (role, password)
    lines = [
        "NidhiSec DEVELOPMENT demo accounts (fictional). Do not reuse these passwords anywhere.",
        "",
        *[f"{role:<15} {email:<45} {password}" for email, (role, password) in entries.items()],
    ]
    CREDENTIALS_FILE.parent.mkdir(parents=True, exist_ok=True)
    CREDENTIALS_FILE.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("\n".join(f"{role:<15} {email}  {password}" for role, email, password in credentials))
    print(f"\nSaved to {CREDENTIALS_FILE} (git-ignored). Delete it when you no longer need it.")
    return 0


# ---------- create-institution / create-user ----------


def cmd_create_institution(args: argparse.Namespace) -> int:
    from app.models import Institution

    db = _open_session()
    try:
        code = args.code.strip().upper()
        if db.scalars(select(Institution).where(Institution.code == code)).one_or_none():
            print(f"Institution {code} already exists.", file=sys.stderr)
            return 1
        inst = Institution(code=code, name=args.name.strip(), contact_email=args.email, state=args.state)
        db.add(inst)
        db.commit()
        print(f"Created institution {inst.code} (id {inst.id}).")
    finally:
        db.close()
    return 0


def cmd_create_user(args: argparse.Namespace) -> int:
    from app.core.security import hash_password
    from app.models import Institution, User, UserRole

    role = UserRole(args.role)
    db = _open_session()
    try:
        email = args.email.strip().lower()
        if db.scalars(select(User).where(User.email == email)).one_or_none():
            print(f"User {email} already exists.", file=sys.stderr)
            return 1
        institution_id = None
        if role == UserRole.INSTITUTION:
            if not args.institution_code:
                print("--institution-code is required for INSTITUTION users.", file=sys.stderr)
                return 1
            inst = db.scalars(
                select(Institution).where(Institution.code == args.institution_code.strip().upper())
            ).one_or_none()
            if inst is None:
                print(f"Institution {args.institution_code} not found.", file=sys.stderr)
                return 1
            institution_id = inst.id

        password = getpass.getpass(f"Password for {email} (min {MIN_PASSWORD_LENGTH} chars): ")
        if len(password) < MIN_PASSWORD_LENGTH or password != getpass.getpass("Repeat password: "):
            print("Passwords must match and be at least 12 characters.", file=sys.stderr)
            return 1
        user = User(
            email=email,
            full_name=args.name.strip(),
            role=role,
            institution_id=institution_id,
            password_hash=hash_password(password),
            is_active=True,
        )
        db.add(user)
        db.commit()
        print(f"Created {role.value} user {email} (id {user.id}).")
    finally:
        db.close()
    return 0


def cmd_lifecycle_check(args: argparse.Namespace) -> int:
    """Create maturity notifications. Idempotent; schedule it daily (e.g. Windows Task Scheduler)."""
    from app.services.lifecycle import run_lifecycle_check

    today = None
    if args.date:
        if not get_settings().is_development:
            print("--date is only available in development.", file=sys.stderr)
            return 1
        today = date.fromisoformat(args.date)
    db = _open_session()
    try:
        counts = run_lifecycle_check(db, actor=None, today=today)
    finally:
        db.close()
    print(", ".join(f"{key}: {value}" for key, value in counts.items()))
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m app.cli", description="NidhiSec management commands")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("init-env", help="Create backend/.env with a freshly generated JWT secret").set_defaults(
        func=cmd_init_env
    )

    seed = sub.add_parser("seed-demo", help="DEVELOPMENT ONLY: create fictional institutions, users and FDRs")
    seed.add_argument("--reset-passwords", action="store_true", help="Generate new passwords for existing demo users")
    seed.add_argument("--no-fdrs", action="store_true", help="Do not create demo FDR records")
    seed.set_defaults(func=cmd_seed_demo)

    inst = sub.add_parser("create-institution", help="Create an institution")
    inst.add_argument("--code", required=True)
    inst.add_argument("--name", required=True)
    inst.add_argument("--email")
    inst.add_argument("--state")
    inst.set_defaults(func=cmd_create_institution)

    user = sub.add_parser("create-user", help="Create a user (password is prompted, never passed as an argument)")
    user.add_argument("--email", required=True)
    user.add_argument("--name", required=True)
    user.add_argument("--role", required=True, choices=["INSTITUTION", "BANK_OFFICER", "AICTE_OFFICIAL"])
    user.add_argument("--institution-code")
    user.set_defaults(func=cmd_create_user)

    check = sub.add_parser("lifecycle-check", help="Create maturity alerts (safe to run repeatedly)")
    check.add_argument("--date", help="DEVELOPMENT ONLY: evaluate as if today were YYYY-MM-DD")
    check.set_defaults(func=cmd_lifecycle_check)

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
