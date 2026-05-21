/**
 * Mirrors backend Pydantic shapes from app/auth/schemas.py.
 * Keep these aligned — drift causes silent JSON mis-mapping at the boundary.
 */

export type UserRole = "user" | "admin";

export interface AuthUser {
  id: number;
  email: string;
  full_name: string | null;
  role: UserRole;
  is_active: boolean;
  created_at: string;
  last_login_at: string | null;
}

export interface AuthSession {
  user: AuthUser;
  /** JWT — kept in memory only, never localStorage. */
  accessToken: string;
  /** Absolute ms epoch when the access token expires (for proactive refresh). */
  expiresAtMs: number;
}

/** Backend /auth/{login,signup,admin-login,refresh} response. */
export interface AuthResponse {
  access_token: string;
  token_type: "bearer";
  expires_in: number; // seconds
  user: AuthUser;
}

/** Backend error envelope ({"detail": "..."}). */
export interface AuthApiError {
  status: number;
  detail: string;
}

export interface SignupFields {
  email: string;
  password: string;
  full_name?: string;
}

export interface LoginFields {
  email: string;
  password: string;
}

export interface ChangePasswordFields {
  current_password: string;
  new_password: string;
}
