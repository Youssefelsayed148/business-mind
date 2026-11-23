import type { ButtonHTMLAttributes } from "react";

type Props = ButtonHTMLAttributes<HTMLButtonElement> & {
  variant?: "primary" | "secondary" | "danger" | "ghost" | "edit" | "pause" | "activate" | "archive" | "stats";
};

const variants = {
  primary: "border-accent bg-accent text-white shadow-sm shadow-emerald-900/10 hover:border-accentHover hover:bg-accentHover hover:shadow-md focus-visible:ring-accent/25 disabled:hover:border-accent disabled:hover:bg-accent",
  secondary: "border-line bg-white text-ink shadow-sm hover:border-slate-300 hover:bg-slate-50 hover:text-slate-950 focus-visible:ring-slate-300/60 disabled:hover:border-line disabled:hover:bg-white",
  danger: "border-danger bg-danger text-white shadow-sm shadow-red-900/10 hover:border-red-600 hover:bg-red-600 hover:shadow-md focus-visible:ring-danger/25 disabled:hover:border-danger disabled:hover:bg-danger",
  ghost: "border-transparent bg-transparent text-slate-200 hover:bg-white/10 hover:text-white focus-visible:ring-white/20",
  edit: "border-blue-200 bg-blue-50 text-blue-700 shadow-sm hover:border-blue-300 hover:bg-blue-100 hover:text-blue-800 focus-visible:ring-blue-200 disabled:hover:border-blue-200 disabled:hover:bg-blue-50",
  pause: "border-slate-700 bg-slate-800 text-white shadow-sm hover:border-slate-800 hover:bg-slate-900 focus-visible:ring-slate-300 disabled:hover:border-slate-700 disabled:hover:bg-slate-800",
  activate: "border-emerald-200 bg-mint text-emerald-700 shadow-sm hover:border-emerald-300 hover:bg-emerald-100 hover:text-emerald-800 focus-visible:ring-emerald-200 disabled:hover:border-emerald-200 disabled:hover:bg-mint",
  archive: "border-red-200 bg-red-50 text-red-700 shadow-sm hover:border-red-300 hover:bg-red-100 hover:text-red-800 focus-visible:ring-red-200 disabled:hover:border-red-200 disabled:hover:bg-red-50",
  stats: "border-violet-200 bg-violet-50 text-violet-700 shadow-sm hover:border-violet-300 hover:bg-violet-100 hover:text-violet-800 focus-visible:ring-violet-200 disabled:hover:border-violet-200 disabled:hover:bg-violet-50",
};

export function Button({ className = "", variant = "primary", ...props }: Props) {
  return (
    <button
      className={`inline-flex h-10 items-center justify-center rounded-lg border px-4 text-sm font-semibold leading-none transition duration-150 ease-out focus-visible:outline-none focus-visible:ring-4 disabled:cursor-not-allowed disabled:opacity-55 ${variants[variant]} ${className}`}
      {...props}
    />
  );
}
