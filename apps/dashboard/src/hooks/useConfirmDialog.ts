/**
 * useConfirmDialog — convenience hook for ConfirmDialog state management
 */

import { useCallback, useEffect, useRef, useState } from "react";

interface ConfirmOptions {
	title: string;
	description: string;
	confirmLabel?: string | undefined;
	cancelLabel?: string | undefined;
	variant?: "danger" | "default" | undefined;
}

export function useConfirmDialog() {
	const [open, setOpen] = useState(false);
	const [options, setOptions] = useState<ConfirmOptions>({
		title: "",
		description: "",
	});
	const resolveRef = useRef<((value: boolean) => void) | null>(null);

	// Resolve pending promise on unmount to prevent memory leak
	useEffect(() => {
		return () => {
			resolveRef.current?.(false);
			resolveRef.current = null;
		};
	}, []);

	const confirm = useCallback((opts: ConfirmOptions): Promise<boolean> => {
		setOptions(opts);
		setOpen(true);
		return new Promise<boolean>((resolve) => {
			resolveRef.current = resolve;
		});
	}, []);

	const onConfirm = useCallback(() => {
		setOpen(false);
		resolveRef.current?.(true);
		resolveRef.current = null;
	}, []);

	const onCancel = useCallback(() => {
		setOpen(false);
		resolveRef.current?.(false);
		resolveRef.current = null;
	}, []);

	return {
		open,
		options,
		confirm,
		onConfirm,
		onCancel,
	};
}
