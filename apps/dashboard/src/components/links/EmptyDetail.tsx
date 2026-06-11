import { Link2 } from "lucide-react";
import { NovaEmpty } from "@/components/ui/NovaPrimitives";

export function EmptyDetail() {
  return (
    <NovaEmpty
      className="min-h-[400px]"
      title="No link selected"
      description="Pick a smart link from the list to edit, track clicks, and build UTMs."
      icon={<Link2 data-icon="inline-start" aria-hidden="true" />}
    />
  );
}
