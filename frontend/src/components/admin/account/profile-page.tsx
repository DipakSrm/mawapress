"use client";

import { Loader2 } from "lucide-react";
import { useState, type FormEvent } from "react";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import { describeError } from "@/lib/admin/errors";
import { MIN_PASSWORD, ROLE_LABEL } from "@/lib/admin/users";
import { api, setAccessToken, type components } from "@/lib/api";
import { useSession, type SessionUser } from "@/lib/auth";

type MeUpdateOut = components["schemas"]["MeUpdateOut"];

const profileError = (e: unknown) =>
  describeError(e, {
    INVALID_CURRENT_PASSWORD: "The current password is not right.",
    NEW_PASSWORD_REQUIRED: "Enter the new password too.",
    PASSWORD_UNCHANGED: "The new password must be different from the current one.",
  });

function ProfileForm({ user }: { user: SessionUser }) {
  const { updateUser } = useSession();
  const [name, setName] = useState(user.name);
  const [bio, setBio] = useState(user.bio ?? "");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function submit(e: FormEvent) {
    e.preventDefault();
    if (busy) return;
    setBusy(true);
    setError(null);
    try {
      const out = await api.patch<MeUpdateOut>("/api/auth/me", { name: name.trim(), bio });
      updateUser({ id: out.id, email: out.email, name: out.name, role: out.role, bio: out.bio });
      setName(out.name);
      setBio(out.bio ?? "");
      toast.success("Profile saved");
    } catch (err) {
      setError(profileError(err));
    } finally {
      setBusy(false);
    }
  }

  return (
    <Card>
      <CardHeader>
        <CardTitle>Your details</CardTitle>
        <CardDescription>
          {user.email} · {ROLE_LABEL[user.role]}. The name and bio appear on the stories you write.
        </CardDescription>
      </CardHeader>
      <CardContent>
        <form onSubmit={(e) => void submit(e)} className="grid max-w-xl gap-4">
          <div className="space-y-1.5">
            <Label htmlFor="profile-name">Name</Label>
            <Input
              id="profile-name"
              required
              maxLength={120}
              value={name}
              onChange={(e) => setName(e.target.value)}
            />
          </div>
          <div className="space-y-1.5">
            <Label htmlFor="profile-bio">Bio</Label>
            <Textarea
              id="profile-bio"
              rows={4}
              maxLength={2000}
              value={bio}
              onChange={(e) => setBio(e.target.value)}
            />
          </div>
          {error && (
            <p role="alert" className="text-sm text-destructive">
              {error}
            </p>
          )}
          <div>
            <Button type="submit" disabled={busy}>
              {busy && <Loader2 aria-hidden className="animate-spin" />}
              Save changes
            </Button>
          </div>
        </form>
      </CardContent>
    </Card>
  );
}

function PasswordForm() {
  const [current, setCurrent] = useState("");
  const [next, setNext] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function submit(e: FormEvent) {
    e.preventDefault();
    if (busy) return;
    if (next.length < MIN_PASSWORD) {
      setError(`The new password needs at least ${MIN_PASSWORD} characters.`);
      return;
    }
    setBusy(true);
    setError(null);
    try {
      const out = await api.patch<MeUpdateOut>("/api/auth/me", {
        current_password: current,
        new_password: next,
      });
      // Every session was revoked except this one, which got a fresh token: keep using it.
      if (out.access_token) setAccessToken(out.access_token);
      setCurrent("");
      setNext("");
      toast.success("Password changed. Your other devices are signed out.");
    } catch (err) {
      setError(profileError(err));
    } finally {
      setBusy(false);
    }
  }

  return (
    <Card>
      <CardHeader>
        <CardTitle>Change password</CardTitle>
        <CardDescription>
          You stay signed in here. Every other device is signed out.
        </CardDescription>
      </CardHeader>
      <CardContent>
        <form onSubmit={(e) => void submit(e)} className="grid max-w-xl gap-4">
          <div className="space-y-1.5">
            <Label htmlFor="current-password">Current password</Label>
            <Input
              id="current-password"
              type="password"
              autoComplete="current-password"
              required
              maxLength={128}
              value={current}
              onChange={(e) => setCurrent(e.target.value)}
            />
          </div>
          <div className="space-y-1.5">
            <Label htmlFor="new-password">New password</Label>
            <Input
              id="new-password"
              type="password"
              autoComplete="new-password"
              required
              maxLength={128}
              value={next}
              onChange={(e) => setNext(e.target.value)}
            />
            <p className="text-xs text-muted-foreground">At least {MIN_PASSWORD} characters.</p>
          </div>
          {error && (
            <p role="alert" className="text-sm text-destructive">
              {error}
            </p>
          )}
          <div>
            <Button type="submit" disabled={busy}>
              {busy && <Loader2 aria-hidden className="animate-spin" />}
              Change password
            </Button>
          </div>
        </form>
      </CardContent>
    </Card>
  );
}

export function ProfilePage() {
  const { user } = useSession();
  if (!user) return null;
  return (
    <div className="space-y-5">
      <div>
        <h1 className="text-2xl font-semibold tracking-tight">Profile</h1>
        <p className="mt-1 text-sm text-muted-foreground">Your account on MAWAPRESS.</p>
      </div>
      <ProfileForm key={user.id} user={user} />
      <PasswordForm />
    </div>
  );
}
