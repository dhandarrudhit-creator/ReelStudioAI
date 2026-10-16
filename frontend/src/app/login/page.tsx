"use client";

import { FormEvent, useState } from "react";
import { useRouter } from "next/navigation";
import Link from "next/link";
import { ApiError, signIn } from "@/lib/api";

export default function LoginPage() {
  const router=useRouter();
  const [mode,setMode]=useState<"login"|"register">("login");
  const [email,setEmail]=useState(""); const [password,setPassword]=useState("");
  const [error,setError]=useState(""); const [busy,setBusy]=useState(false);
  async function submit(event:FormEvent<HTMLFormElement>) {
    event.preventDefault(); setError(""); setBusy(true);
    try { await signIn(email,password,mode); router.replace("/"); }
    catch(e) { setError(e instanceof ApiError ? e.message : "Could not sign in."); }
    finally { setBusy(false); }
  }
  return <main className="auth-page">
    <section className="auth-showcase">
      <Link className="brand" href="/"><span className="brand-symbol"><Mark/></span><span>reel<span className="brand-lilac">studio</span></span></Link>
      <div className="auth-message"><span className="eyebrow"><i/> YOUR TEACHING, IN FOCUS</span><h1>Good lessons<br/>deserve a <em>second life.</em></h1><p>Shape your classroom recordings into thoughtful, shareable moments. Your source files stay on your machine.</p></div>
      <div className="auth-showcase-foot"><span className="privacy-dot"/> Local-first workspace <span>·</span> No paid AI APIs</div>
      <div className="auth-orb" aria-hidden="true"/><div className="auth-grid" aria-hidden="true"/>
    </section>
    <section className="auth-form-side"><form className="auth-form" onSubmit={submit}>
      <div className="auth-form-title"><span className="eyebrow">WELCOME TO THE STUDIO</span><h2>{mode==="login"?"Pick up where you left off.":"Create your studio account."}</h2><p>{mode==="login"?"Sign in to continue to your projects.":"Your project history is saved to this device."}</p></div>
      <label>Email address<input autoComplete="email" type="email" value={email} onChange={e=>setEmail(e.target.value)} required placeholder="you@school.edu"/></label>
      <label>Password<input autoComplete={mode==="login"?"current-password":"new-password"} type="password" value={password} onChange={e=>setPassword(e.target.value)} required minLength={8} placeholder="At least 8 characters"/></label>
      {error&&<div className="form-error" role="alert">{error}</div>}
      <button className="button button-primary auth-submit" disabled={busy}>{busy?<><span className="spinner"/> Working…</>:mode==="login"?"Sign in to workspace":"Create account"}<span aria-hidden="true">→</span></button>
      <p className="auth-switch">{mode==="login"?"New to Reel Studio?":"Already have an account?"} <button type="button" onClick={()=>{setMode(mode==="login"?"register":"login");setError("")}}>{mode==="login"?"Create an account":"Sign in"}</button></p>
      <p className="auth-note">Local MVP account · no email verification · data stored in this app’s SQLite database.</p>
    </form><span className="auth-copyright">REEL STUDIO AI <span>©</span> 2026</span></section>
  </main>;
}

function Mark(){return <svg viewBox="0 0 24 24" fill="none" aria-hidden="true"><path d="M6 4.5h12A2.5 2.5 0 0 1 20.5 7v10a2.5 2.5 0 0 1-2.5 2.5H6A2.5 2.5 0 0 1 3.5 17V7A2.5 2.5 0 0 1 6 4.5Z"/><path d="m10 8.5 5.5 3.5-5.5 3.5v-7Z"/></svg>}
