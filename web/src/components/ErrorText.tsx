/** A failed request's text from the one error path in `client.ts` (`CODE: message`, `HTTP <status>`, `API unreachable`). */
export function ErrorText({ message, className }: { message: string; className?: string }) {
  return (
    <p className={className ? `error ${className}` : "error"} role="alert">
      {message}
    </p>
  );
}
