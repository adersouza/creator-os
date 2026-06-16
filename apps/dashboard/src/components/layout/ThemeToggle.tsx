import { useEffect, useMemo, useState } from "react";
import { Moon, Sun } from "lucide-react";
import { Button } from "@/components/ui/Button";
import {
	applyThemeChoice,
	persistThemeToRemote,
	readThemeChoiceFromStorage,
	resolveThemeChoice,
	THEME_CHANGE_EVENT,
	type ThemeChoice,
} from "@/lib/themeSync";
import { cn } from "@/lib/utils";

type ThemeToggleProps = {
	variant?: "icon" | "row" | undefined;
	className?: string | undefined;
};

export function ThemeToggle({ variant = "icon", className }: ThemeToggleProps) {
	const [choice, setChoice] = useState<ThemeChoice>(() => readThemeChoiceFromStorage());
	const [resolved, setResolved] = useState<"light" | "dark">(() => resolveThemeChoice(choice));

	useEffect(() => {
		const refresh = () => {
			const nextChoice = readThemeChoiceFromStorage();
			setChoice(nextChoice);
			setResolved(resolveThemeChoice(nextChoice));
		};

		const media = window.matchMedia("(prefers-color-scheme: dark)");
		const onMediaChange = () => {
			if (readThemeChoiceFromStorage() === "system") refresh();
		};

		window.addEventListener(THEME_CHANGE_EVENT, refresh);
		window.addEventListener("storage", refresh);
		media.addEventListener("change", onMediaChange);
		refresh();

		return () => {
			window.removeEventListener(THEME_CHANGE_EVENT, refresh);
			window.removeEventListener("storage", refresh);
			media.removeEventListener("change", onMediaChange);
		};
	}, []);

	const nextChoice = useMemo<ThemeChoice>(() => (resolved === "dark" ? "light" : "dark"), [resolved]);
	const Icon = resolved === "dark" ? Sun : Moon;
	const label = resolved === "dark" ? "Switch to light mode" : "Switch to dark mode";

	const toggleTheme = () => {
		const nextResolved = applyThemeChoice(nextChoice);
		setChoice(nextChoice);
		setResolved(nextResolved);
		void persistThemeToRemote(nextChoice);
	};

	if (variant === "row") {
		return (
			<Button
				type="button"
				variant="ghost"
				onClick={toggleTheme}
				className={cn("h-auto w-full justify-start gap-3 rounded-lg px-3 py-3 text-left", className)}
				aria-label={label}
			>
				<Icon data-icon="inline-start" aria-hidden="true" />
				<span className="min-w-0 flex-1">
					<span className="block text-sm font-medium text-foreground">Theme</span>
					<span className="block truncate text-xs text-muted-foreground">
						{choice === "system" ? `System, currently ${resolved}` : `${resolved} mode`}
					</span>
				</span>
			</Button>
		);
	}

	return (
		<Button
			type="button"
			variant="ghost"
			size="icon"
			onClick={toggleTheme}
			className={className}
			aria-label={label}
			title={label}
		>
			<Icon aria-hidden="true" />
		</Button>
	);
}
