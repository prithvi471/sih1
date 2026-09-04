"""Auth + RBAC: login, bad credentials, permissions, subsidiary scoping."""
from conftest import ING, get, post, login


def test_login_ok(admin):
    assert admin


def test_bad_password_rejected():
    st, _ = post(f"{ING}/auth/login", body={"username": "admin", "password": "WRONG"})
    assert st == 401


def test_me_returns_permissions(admin):
    st, d = get(f"{ING}/auth/me", token=admin)
    assert st == 200
    assert d["role"] == "ADMIN"
    assert "permissions" in d


def test_admin_can_read_users(admin):
    st, d = get(f"{ING}/auth/users", token=admin)
    assert st == 200
    assert isinstance(d, list) and len(d) >= 1


def test_subsidiary_officer_cannot_read_users(mcl):
    st, _ = get(f"{ING}/auth/users", token=mcl)
    assert st == 403


def test_auditor_can_read_users_not_write():
    au = login("auditor_user")
    st, _ = get(f"{ING}/auth/users", token=au)
    assert st == 200
    st, _ = post(f"{ING}/auth/users", token=au,
                 body={"username": "x", "password": "x12345", "full_name": "X", "role": "VIEWER"})
    assert st == 403
