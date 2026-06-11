import { NovaEmpty } from "@/components/ui/NovaPrimitives";

export function UnavailablePanel({ label }: { label: string }) {
  return (
    <NovaEmpty
      title={label}
      description="Refresh the library to retry."
      className="min-h-[16rem]"
    />
  );
}
