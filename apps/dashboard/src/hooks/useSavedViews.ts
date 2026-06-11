/**
 * useSavedViews — React Query wrapper over the /api/saved-views surface.
 * Exposes list + create + delete with optimistic-ish cache invalidation.
 */

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useAuthUser } from "@/hooks/useAuthUser";
import {
	type SavedView,
	type SavedViewFilters,
	createSavedView,
	deleteSavedView,
	listSavedViews,
} from "@/services/savedViewsService";

const QUERY_KEY = ["savedViews", "analytics"] as const;

export function useSavedViews() {
	const user = useAuthUser();
	const qc = useQueryClient();

	const query = useQuery({
		queryKey: QUERY_KEY,
		queryFn: () => listSavedViews("analytics"),
		enabled: !!user,
		staleTime: 5 * 60_000,
	});

	const saveMutation = useMutation({
		mutationFn: (args: { name: string; filters: SavedViewFilters }) =>
			createSavedView(args),
		onSuccess: (view) => {
			qc.setQueryData<SavedView[]>(QUERY_KEY, (prev) =>
				prev ? [view, ...prev.filter((v) => v.id !== view.id)] : [view],
			);
		},
	});

	const deleteMutation = useMutation({
		mutationFn: (id: string) => deleteSavedView(id),
		onSuccess: (_data, id) => {
			qc.setQueryData<SavedView[]>(QUERY_KEY, (prev) =>
				prev ? prev.filter((v) => v.id !== id) : prev,
			);
		},
	});

	return {
		views: query.data ?? [],
		loading: query.isPending && !!user,
		error: query.error,
		save: saveMutation.mutateAsync,
		saveState: { loading: saveMutation.isPending, error: saveMutation.error },
		remove: deleteMutation.mutateAsync,
		removeState: {
			loading: deleteMutation.isPending,
			error: deleteMutation.error,
		},
	};
}
