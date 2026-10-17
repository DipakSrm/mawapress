import Image from "next/image";

export default function PublicHome() {
  return (
    <main className="mx-auto flex min-h-screen max-w-3xl flex-col items-center justify-center gap-6 px-4 text-center">
      <Image
        src="/brand/mawapress-logo.svg"
        alt="MAWAPRESS"
        width={480}
        height={120}
        priority
        className="h-auto w-full max-w-md dark:rounded-xl dark:bg-white dark:p-3"
      />
      <h1 className="text-3xl font-semibold tracking-tight">MAWAPRESS</h1>
      <p lang="ne" className="text-muted-foreground">
        मोरङको आवाज
      </p>
      <p className="text-sm text-muted-foreground">The public site is coming soon.</p>
    </main>
  );
}
