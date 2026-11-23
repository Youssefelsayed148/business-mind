import { api } from "./api";
import type { User } from "./types";

export function getAccessToken(): string | null {
  if (typeof window === "undefined") return null;
  return window.localStorage.getItem("access_token");
}

export function setAccessToken(token: string) {
  window.localStorage.setItem("access_token", token);
}

export function clearAccessToken() {
  window.localStorage.removeItem("access_token");
}

export async function login(email: string, password: string) {
  const body = new URLSearchParams();
  body.set("username", email);
  body.set("password", password);
  return api.post<{ access_token: string; token_type: string }>("/auth/login", body);
}

export async function getMe() {
  return api.get<User>("/auth/me");
}
