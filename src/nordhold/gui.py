from __future__ import annotations

import importlib
import threading
import tkinter as tk
import tkinter.font as tk_font
from pathlib import Path
from tkinter import filedialog, messagebox, ttk
from typing import Dict, List, Optional, Tuple

from . import calculator, config, formatting
from .calculator import evaluate_lineup, search_best_lineups, tower_variants_map
from .config import ConfigError, load_config
from .formatting import format_lineup_details, summarize_modifiers, summarize_towers


class NordholdApp:
    def __init__(self, root: tk.Tk):
        self.root = root
        self.root.title("Nordhold Damage Calculator")
        self.root.geometry("1220x780")
        self.root.minsize(960, 640)

        style = ttk.Style(self.root)
        if "clam" in style.theme_names():
            style.theme_use("clam")
        
        # Configure larger, more visible buttons
        style.configure("Action.TButton", 
            font=("TkDefaultFont", 11, "bold"),
            padding=(12, 6))

        self.config: Optional[Config] = None
        self.variants_map: Dict[str, Tuple] = {}
        self.manual_tower_rows: List[Dict] = []
        self.manual_modifier_groups: Dict[str, Dict] = {}
        self.auto_results: Dict[str, object] = {}
        
        # Threading tracking
        self.autopick_thread: Optional[threading.Thread] = None
        self.calculation_active = threading.Event()
        
        # Scaling
        self.base_width = 1220
        self.scale_factor = 1.0

        default_config = Path("data/sample_config.json")
        self.config_path_var = tk.StringVar(value=str(default_config))
        self.top_n_var = tk.IntVar(value=5)
        self.max_cost_var = tk.StringVar(value="")
        self.manual_summary_var = tk.StringVar(
            value='Сформируйте связку и нажмите «Рассчитать», чтобы увидеть детализацию урона.'
        )
        self.status_var = tk.StringVar(
            value="Загрузите конфигурацию и заполните параметры. Используются примерные названия — замените их на реальные данные из игры."
        )

        self._build_layout()
        self._init_scaling()
        self._load_config_from_path(default_config, show_error=False)

    # ------------------------------------------------------------------ UI
    def _build_layout(self) -> None:
        root = self.root
        root.columnconfigure(0, weight=1)
        root.rowconfigure(1, weight=1)

        control_bar = ttk.Frame(root, padding=(16, 12, 16, 8))
        control_bar.grid(row=0, column=0, sticky="ew")
        control_bar.columnconfigure(1, weight=1)

        ttk.Label(control_bar, text="Конфигурация:").grid(row=0, column=0, sticky="w")
        ttk.Entry(control_bar, textvariable=self.config_path_var).grid(
            row=0, column=1, sticky="ew", padx=(8, 8)
        )
        ttk.Button(control_bar, text="Обзор...", command=self._browse_config).grid(
            row=0, column=2, padx=(0, 8)
        )
        ttk.Button(control_bar, text="Загрузить", command=self._reload_config).grid(
            row=0, column=3, padx=(0, 8)
        )
        ttk.Button(control_bar, text="🔄 Reload Code", command=self._reload_code_modules).grid(
            row=0, column=4
        )

        notebook = ttk.Notebook(root)
        notebook.grid(row=1, column=0, sticky="nsew")

        self.manual_tab = ttk.Frame(notebook, padding=12)
        self.auto_tab = ttk.Frame(notebook, padding=12)
        self.manual_tab.columnconfigure(0, weight=1)
        self.manual_tab.rowconfigure(0, weight=1)
        self.auto_tab.columnconfigure(0, weight=1)
        self.auto_tab.rowconfigure(0, weight=1)

        notebook.add(self.manual_tab, text="Ручной расчёт")
        notebook.add(self.auto_tab, text="Автоподбор")

        self._build_manual_tab()
        self._build_auto_tab()

        status_bar = ttk.Frame(root, padding=(16, 4, 16, 12))
        status_bar.grid(row=2, column=0, sticky="ew")
        ttk.Label(status_bar, textvariable=self.status_var, anchor="w").pack(fill="x")

    def _init_scaling(self) -> None:
        """Initialize scaling system and bind resize events"""
        # Bind window resize event
        self.root.bind('<Configure>', self._on_resize)
        
        # Store default fonts for scaling
        self.default_font = tk_font.nametofont("TkDefaultFont")
        self.heading_font = tk_font.nametofont("TkHeadingFont")
        self.caption_font = tk_font.nametofont("TkCaptionFont")
        
        # Store original sizes
        self.original_font_size = self.default_font.cget('size')
        
    def _on_resize(self, event) -> None:
        """Handle window resize events for dynamic scaling"""
        if event.widget == self.root:
            new_width = event.width
            if new_width > 0:
                # Calculate scale factor based on width
                self.scale_factor = new_width / self.base_width
                
                # Update font sizes (clamp between 0.8 and 1.3)
                scale = max(0.8, min(1.3, self.scale_factor))
                new_size = int(self.original_font_size * scale)
                self.default_font.configure(size=new_size)

    def _build_manual_tab(self) -> None:
        split = ttk.Panedwindow(self.manual_tab, orient=tk.HORIZONTAL)
        split.grid(row=0, column=0, sticky="nsew")

        controls = ttk.Frame(split, padding=(0, 0, 12, 0))
        controls.columnconfigure(0, weight=1)

        self.manual_towers_frame = ttk.LabelFrame(controls, text="Башни", padding=12)
        self.manual_towers_frame.grid(row=0, column=0, sticky="ew")
        self.manual_towers_frame.columnconfigure(2, weight=1)
        self.manual_intro_label = ttk.Label(
            self.manual_towers_frame,
            text="Укажите количество башен и глубину апгрейда. Комбинации учитывают лимиты из конфигурации.",
            foreground="#444444",
            wraplength=360,
            justify="left",
        )
        self.manual_intro_label.grid(row=0, column=0, columnspan=3, sticky="w", pady=(0, 6))

        self.manual_modifiers_container = ttk.LabelFrame(
            controls, text="Модификаторы", padding=12
        )
        self.manual_modifiers_container.grid(row=1, column=0, sticky="ew", pady=(12, 0))
        self.manual_modifiers_container.columnconfigure(0, weight=1)

        buttons = ttk.Frame(controls, padding=(0, 12, 0, 0))
        buttons.grid(row=2, column=0, sticky="ew")
        buttons.grid_propagate(False)  # Don't shrink buttons frame
        ttk.Button(buttons, text="Рассчитать", command=self._calculate_manual, style="Action.TButton").pack(
            side="left", pady=4, padx=8
        )
        ttk.Button(buttons, text="Сбросить", command=self._reset_manual_selection, style="Action.TButton").pack(
            side="left", padx=8, pady=4
        )

        split.add(controls, weight=3)

        result_frame = ttk.LabelFrame(split, text="Результат", padding=12)
        result_frame.columnconfigure(0, weight=1)
        result_frame.rowconfigure(1, weight=1)

        ttk.Label(
            result_frame,
            textvariable=self.manual_summary_var,
            anchor="w",
            wraplength=420,
        ).grid(row=0, column=0, sticky="ew")

        self.manual_text = tk.Text(result_frame, wrap="word", height=18)
        manual_scroll = ttk.Scrollbar(result_frame, orient="vertical", command=self.manual_text.yview)
        self.manual_text.configure(yscrollcommand=manual_scroll.set, state="disabled")
        self.manual_text.grid(row=1, column=0, sticky="nsew", pady=(8, 0))
        manual_scroll.grid(row=1, column=1, sticky="ns", pady=(8, 0))

        split.add(result_frame, weight=2)

    def _build_auto_tab(self) -> None:
        top = ttk.Frame(self.auto_tab)
        top.pack(fill="x")

        ttk.Label(top, text="Top N:").grid(row=0, column=0, padx=(0, 6))
        ttk.Spinbox(top, from_=1, to=50, textvariable=self.top_n_var, width=6).grid(
            row=0, column=1, padx=(0, 16)
        )

        ttk.Label(top, text="Макс. стоимость:").grid(row=0, column=2)
        ttk.Entry(top, textvariable=self.max_cost_var, width=12).grid(
            row=0, column=3, padx=(6, 16)
        )

        self._autopick_button = ttk.Button(top, text="Подобрать", command=self._run_autopick, style="Action.TButton")
        self._autopick_button.grid(row=0, column=4)

        ttk.Label(
            self.auto_tab,
            text="Автоподбор перебирает разрешённые связки и выводит топ по DPS. "
            "Используйте параметры выше, чтобы ограничить выдачу.",
            foreground="#444444",
            wraplength=600,
            justify="left",
        ).pack(anchor="w", pady=(10, 0))

        self.auto_progress = ttk.Progressbar(self.auto_tab, mode="determinate")
        self.auto_progress.pack(fill="x", pady=(6, 8))

        tree_frame = ttk.Frame(self.auto_tab, padding=(0, 12, 0, 0))
        tree_frame.pack(fill="both", expand=True)
        tree_frame.rowconfigure(0, weight=1)
        tree_frame.columnconfigure(0, weight=1)

        columns = ("rank", "dps", "cost", "towers", "modifiers")
        self.auto_tree = ttk.Treeview(tree_frame, columns=columns, show="headings")

        headings = {
            "rank": "Rank",
            "dps": "Total DPS",
            "cost": "Total Cost",
            "towers": "Towers",
            "modifiers": "Modifiers",
        }
        for column, title in headings.items():
            self.auto_tree.heading(
                column,
                text=title,
                command=lambda col=column: self._sort_tree(self.auto_tree, col, False),
            )

        self.auto_tree.column("rank", width=60, anchor="center", stretch=False)
        self.auto_tree.column("dps", width=110, anchor="e", stretch=False)
        self.auto_tree.column("cost", width=110, anchor="e", stretch=False)
        self.auto_tree.column("towers", width=320, anchor="w", stretch=True)
        self.auto_tree.column("modifiers", width=360, anchor="w", stretch=True)

        y_scroll = ttk.Scrollbar(tree_frame, orient="vertical", command=self.auto_tree.yview)
        x_scroll = ttk.Scrollbar(tree_frame, orient="horizontal", command=self.auto_tree.xview)
        self.auto_tree.configure(yscrollcommand=y_scroll.set, xscrollcommand=x_scroll.set)

        self.auto_tree.grid(row=0, column=0, sticky="nsew")
        y_scroll.grid(row=0, column=1, sticky="ns")
        x_scroll.grid(row=1, column=0, sticky="ew")

        self.auto_tree.bind("<<TreeviewSelect>>", self._on_autopick_select)

        detail_frame = ttk.LabelFrame(self.auto_tab, text="Детали", padding=12)
        detail_frame.pack(fill="both", expand=True, pady=(12, 0))
        detail_frame.rowconfigure(0, weight=1)
        detail_frame.columnconfigure(0, weight=1)

        self.auto_text = tk.Text(detail_frame, wrap="word", height=14)
        auto_scroll = ttk.Scrollbar(detail_frame, orient="vertical", command=self.auto_text.yview)
        self.auto_text.configure(yscrollcommand=auto_scroll.set, state="disabled")
        self.auto_text.grid(row=0, column=0, sticky="nsew")
        auto_scroll.grid(row=0, column=1, sticky="ns")

    # ------------------------------------------------------------------ Config helpers
    def _browse_config(self) -> None:
        initial_dir = Path(self.config_path_var.get()).expanduser().parent
        file_path = filedialog.askopenfilename(
            title="Выберите конфигурацию",
            initialdir=initial_dir,
            filetypes=(
                ("JSON", "*.json"),
                ("YAML", "*.yml *.yaml"),
                ("Все файлы", "*.*"),
            ),
        )
        if file_path:
            self.config_path_var.set(file_path)

    def _reload_config(self) -> None:
        self._load_config_from_path(Path(self.config_path_var.get()).expanduser(), show_error=True)
    
    def _reload_code_modules(self) -> None:
        """Hot reload Python modules without restarting app"""
        try:
            import sys
            import os
            
            # Reload modules
            importlib.reload(calculator)
            importlib.reload(config)
            importlib.reload(formatting)
            
            # Re-import functions
            global evaluate_lineup, search_best_lineups, tower_variants_map, ConfigError, load_config
            global format_lineup_details, summarize_modifiers, summarize_towers
            
            from .calculator import evaluate_lineup, search_best_lineups, tower_variants_map
            from .config import ConfigError, load_config  
            from .formatting import format_lineup_details, summarize_modifiers, summarize_towers
            
            # Update status
            self.status_var.set("Код перезагружен. Изменения применены.")
            
            # Rebuild UI to pick up any changes
            if self.config:
                self.variants_map = tower_variants_map(self.config)
                self._rebuild_manual_controls()
                self._clear_autopick_results()
            
            messagebox.showinfo("Перезагрузка", "Модули Python перезагружены успешно!")
            
        except Exception as exc:
            messagebox.showerror("Ошибка перезагрузки", f"Не удалось перезагрузить код: {exc}")

    def _load_config_from_path(self, path: Path, show_error: bool) -> None:
        if not path.exists():
            if show_error:
                messagebox.showerror("Ошибка", f"Файл не найден: {path}")
            return
        try:
            config = load_config(path)
        except ConfigError as exc:
            if show_error:
                messagebox.showerror("Ошибка конфигурации", str(exc))
            return
        except Exception as exc:
            if show_error:
                messagebox.showerror("Ошибка", str(exc))
            return

        self.config = config
        self.variants_map = tower_variants_map(config)
        self._rebuild_manual_controls()
        self._clear_autopick_results()
        self.status_var.set(
            f"Загружена конфигурация: {path.name}. Проверьте названия башен и модификаторов, чтобы они совпадали с игрой."
        )

    # ------------------------------------------------------------------ Manual calculation
    def _rebuild_manual_controls(self) -> None:
        for widget in list(self.manual_towers_frame.winfo_children()):
            if widget is self.manual_intro_label:
                continue
            widget.destroy()
        for widget in self.manual_modifiers_container.winfo_children():
            widget.destroy()

        self.manual_tower_rows = []
        self.manual_modifier_groups = {}
        self.manual_summary_var.set(
            'Сформируйте связку и нажмите «Рассчитать», чтобы увидеть детализацию урона.'
        )
        self._set_manual_text("")

        if not self.config:
            return

        start_row = 1
        for row_idx, tower in enumerate(self.config.towers, start=start_row):
            variants = self.variants_map.get(tower.name, ())
            if not variants:
                continue
            container = ttk.Frame(self.manual_towers_frame)
            container.grid(row=row_idx, column=0, columnspan=3, sticky="ew", pady=2)
            container.columnconfigure(2, weight=1)

            ttk.Label(container, text=tower.name, width=22).grid(row=0, column=0, sticky="w")

            count_var = tk.IntVar(value=0)
            spin = ttk.Spinbox(
                container,
                from_=0,
                to=tower.max_count,
                textvariable=count_var,
                width=5,
                command=self._refresh_manual_limits,
            )
            spin.grid(row=0, column=1, padx=(8, 8))
            spin.bind(
                "<FocusOut>",
                lambda _event, var=count_var, maximum=tower.max_count: self._clamp_spin(var, maximum),
            )

            labels = []
            for level, variant in enumerate(variants):
                if level == 0:
                    label = "0 — без апгрейдов"
                else:
                    path = " -> ".join(upgrade.name for upgrade in variant.upgrades)
                    label = f"{level} — {path}"
                labels.append(label)

            combo = ttk.Combobox(container, values=labels, state="readonly", width=38)
            combo.current(0)
            combo.grid(row=0, column=2, sticky="ew")

            self.manual_tower_rows.append(
                {
                    "tower": tower,
                    "variants": variants,
                    "count_var": count_var,
                    "combo": combo,
                }
            )

        for category, modifiers in self.config.modifiers.items():
            group_frame = ttk.LabelFrame(
                self.manual_modifiers_container,
                text=f"{category} (лимиты учитываются автоматически)",
                padding=(12, 8),
            )
            group_frame.pack(fill="x", pady=4)

            limit = self.config.selection_limits.limit_for(category, default=len(modifiers))
            limit_label = ttk.Label(group_frame, text="")
            limit_label.pack(anchor="w")

            rows = []
            for modifier in modifiers:
                row = ttk.Frame(group_frame)
                row.pack(fill="x", pady=2)
                ttk.Label(row, text=modifier.name, width=28).pack(side="left")
                var = tk.IntVar(value=0)
                spin = ttk.Spinbox(
                    row,
                    from_=0,
                    to=modifier.max_stacks,
                    textvariable=var,
                    width=5,
                    command=lambda cat=category: self._refresh_modifier_usage(cat),
                )
                spin.pack(side="left", padx=6)
                spin.bind(
                    "<FocusOut>",
                    lambda _event, value_var=var, maximum=modifier.max_stacks, cat=category: self._clamp_modifier(
                        value_var, maximum, cat
                    ),
                )
                if modifier.notes:
                    ttk.Label(row, text=modifier.notes, foreground="#555555").pack(side="left", padx=(6, 0))
                rows.append({"modifier": modifier, "var": var})

            self.manual_modifier_groups[category] = {
                "limit": limit,
                "label": limit_label,
                "rows": rows,
            }
            self._refresh_modifier_usage(category)

    def _clamp_spin(self, var: tk.IntVar, maximum: int) -> None:
        try:
            value = int(var.get())
        except Exception:
            value = 0
        var.set(max(0, min(value, maximum)))
        self._refresh_manual_limits()

    def _clamp_modifier(self, var: tk.IntVar, maximum: int, category: str) -> None:
        try:
            value = int(var.get())
        except Exception:
            value = 0
        var.set(max(0, min(value, maximum)))
        self._refresh_modifier_usage(category)

    def _refresh_manual_limits(self) -> None:
        # Зарезервировано под дополнительные проверки (например, лимит слотов арены).
        pass

    def _refresh_modifier_usage(self, category: str) -> None:
        group = self.manual_modifier_groups.get(category)
        if not group:
            return
        limit = group["limit"]
        total = sum(max(0, entry["var"].get()) for entry in group["rows"])
        if limit > 0:
            color = "red" if total > limit else "#333333"
            group["label"].configure(text=f"Выбрано {total} из {limit}", foreground=color)
        else:
            group["label"].configure(text=f"Выбрано {total}; ограничений нет", foreground="#333333")

    def _reset_manual_selection(self) -> None:
        for entry in self.manual_tower_rows:
            entry["count_var"].set(0)
            entry["combo"].current(0)
        for category in self.manual_modifier_groups.keys():
            for entry in self.manual_modifier_groups[category]["rows"]:
                entry["var"].set(0)
            self._refresh_modifier_usage(category)
        self.manual_summary_var.set(
            'Сформируйте связку и нажмите «Рассчитать», чтобы увидеть детализацию урона.'
        )
        self._set_manual_text("")

    def _calculate_manual(self) -> None:
        if not self.config:
            messagebox.showerror("Ошибка", "Сначала загрузите конфигурацию.")
            return

        lineup = []
        for entry in self.manual_tower_rows:
            count = max(0, int(entry["count_var"].get()))
            if count == 0:
                continue
            variants = entry["variants"]
            level_index = max(0, min(entry["combo"].current(), len(variants) - 1))
            lineup.extend([variants[level_index]] * count)

        if not lineup:
            messagebox.showinfo("Нет башен", "Выберите хотя бы одну башню.")
            return

        selection: Dict[str, Tuple] = {}
        for category, group in self.manual_modifier_groups.items():
            chosen: List = []
            for entry in group["rows"]:
                quantity = max(0, int(entry["var"].get()))
                if quantity:
                    chosen.extend([entry["modifier"]] * quantity)
            limit = group["limit"]
            if limit > 0 and len(chosen) > limit:
                messagebox.showerror(
                    "Превышен лимит",
                    f"Категория '{category}' допускает максимум {limit} предметов. Уменьшите выбор.",
                )
                return
            if chosen:
                selection[category] = tuple(chosen)

        result = evaluate_lineup(lineup, selection, self.config)
        self.manual_summary_var.set(
            f"Total DPS: {result.total_dps:.2f} | Total Cost: {result.total_cost:.2f}"
        )
        self._set_manual_text(format_lineup_details(result))
        self._set_status("Ручной расчёт выполнен.")

    def _set_manual_text(self, text: str) -> None:
        self.manual_text.configure(state="normal")
        self.manual_text.delete("1.0", tk.END)
        if text:
            self.manual_text.insert(tk.END, text)
        self.manual_text.configure(state="disabled")

    # ------------------------------------------------------------------ Autopick
    def _run_autopick(self) -> None:
        if not self.config:
            messagebox.showerror("Ошибка", "Сначала загрузите конфигурацию.")
            return
        
        # Don't allow multiple simultaneous calculations
        if self.autopick_thread and self.autopick_thread.is_alive():
            return
            
        self._reset_autopick_progress()

        try:
            top_n = max(1, int(self.top_n_var.get()))
        except (TypeError, ValueError):
            messagebox.showerror("Ошибка", "Поле Top N должно быть целым числом.")
            return

        raw_cost = self.max_cost_var.get().strip()
        if raw_cost:
            try:
                max_cost = float(raw_cost.replace(",", "."))
            except ValueError:
                messagebox.showerror("Ошибка", "Максимальная стоимость должна быть числом.")
                return
        else:
            max_cost = None
        
        # Disable autopick button during calculation
        self._autopick_button.configure(state='disabled')
        self.calculation_active.set()
        
        # Store parameters for thread
        self._thread_params = {
            'top_n': top_n,
            'max_cost': max_cost,
            'results': [],
            'progress': [0, 0],
            'error': None,
            'done': False
        }
        
        # Launch calculation in separate thread
        self.autopick_thread = threading.Thread(
            target=self._calculate_in_thread,
            daemon=True
        )
        self.autopick_thread.start()
        
        # Start polling for results
        self._poll_autopick_thread()
    
    def _calculate_in_thread(self) -> None:
        """Run calculation in background thread"""
        params = self._thread_params
        try:
            def progress_hook(done: int, total: int) -> None:
                params['progress'] = [done, total]
            
            results = search_best_lineups(
                self.config,
                top_n=params['top_n'],
                max_cost=params['max_cost'],
                progress_callback=progress_hook,
            )
            params['results'] = results
            params['done'] = True
        except Exception as exc:
            params['error'] = str(exc)
            params['done'] = True
        
    def _poll_autopick_thread(self) -> None:
        """Poll thread for progress updates"""
        if not self.autopick_thread or not hasattr(self, '_thread_params'):
            return
        
        params = self._thread_params
        
        # Update progress bar
        if params['progress'][1] > 0:
            self.auto_progress["maximum"] = params['progress'][1]
            self.auto_progress["value"] = params['progress'][0]
        
        # Check if thread is done
        if params['done']:
            if params['error']:
                messagebox.showerror("Сбой расчёта", params['error'])
            else:
                results = params['results']
                self.auto_progress["value"] = self.auto_progress["maximum"]
                self._populate_autopick_results(results)
                if results:
                    self._set_status(f"Найдено комбинаций: {len(results)}.")
                else:
                    self._set_status("Подходящих комбинаций не найдено.")
            
            # Re-enable button
            self._autopick_button.configure(state='normal')
            self.autopick_thread = None
            self.calculation_active.clear()
        else:
            # Thread still running, check again in 50ms
            self.root.after(50, self._poll_autopick_thread)

    def _populate_autopick_results(self, results) -> None:
        """Populate results from LineupEvaluation objects (legacy method)"""
        self._clear_autopick_results()
        for index, result in enumerate(results, start=1):
            iid = str(index)
            self.auto_tree.insert(
                "",
                "end",
                iid=iid,
                values=(
                    index,
                    f"{result.total_dps:.2f}",
                    f"{result.total_cost:.2f}",
                    summarize_towers(result.towers),
                    summarize_modifiers(result.modifier_selection),
                ),
            )
            self.auto_results[iid] = result

        if results:
            first = "1"
            self.auto_tree.selection_set(first)
            self.auto_tree.focus(first)
            self.auto_tree.see(first)
            self._display_autopick_detail(results[0])
    
    def _populate_autopick_results_from_dicts(self, results_dicts) -> None:
        """Populate results from dictionaries (multiprocessing)"""
        self._clear_autopick_results()
        for index, result_dict in enumerate(results_dicts, start=1):
            iid = str(index)
            
            # Format towers summary
            towers_summary = ", ".join([f"{t['display_name']} x1" for t in result_dict['towers']])
            
            # Format modifiers summary
            mods_parts = []
            for category, mods in result_dict['modifier_selection'].items():
                mod_names = ", ".join([m['name'] for m in mods])
                if mod_names:
                    mods_parts.append(f"{category}: {mod_names}")
            mods_summary = " | ".join(mods_parts) if mods_parts else "none"
            
            self.auto_tree.insert(
                "",
                "end",
                iid=iid,
                values=(
                    index,
                    f"{result_dict['total_dps']:.2f}",
                    f"{result_dict['total_cost']:.2f}",
                    towers_summary,
                    mods_summary,
                ),
            )
            self.auto_results[iid] = result_dict

        if results_dicts:
            first = "1"
            self.auto_tree.selection_set(first)
            self.auto_tree.focus(first)
            self.auto_tree.see(first)
            self._display_autopick_detail_from_dict(results_dicts[0])

    def _clear_autopick_results(self) -> None:
        for item in self.auto_tree.get_children():
            self.auto_tree.delete(item)
        self.auto_results.clear()
        self.auto_text.configure(state="normal")
        self.auto_text.delete("1.0", tk.END)
        self.auto_text.configure(state="disabled")
        self._reset_autopick_progress()

    def _on_autopick_select(self, _event) -> None:
        selected = self.auto_tree.selection()
        if not selected:
            return
        result = self.auto_results.get(selected[0])
        if result:
            self._display_autopick_detail(result)

    def _display_autopick_detail(self, result) -> None:
        payload = format_lineup_details(result)
        self.auto_text.configure(state="normal")
        self.auto_text.delete("1.0", tk.END)
        self.auto_text.insert(tk.END, payload)
        self.auto_text.configure(state="disabled")
    
    def _display_autopick_detail_from_dict(self, result_dict) -> None:
        """Display detail for dict-based result"""
        lines = []
        lines.append(f"Total DPS: {result_dict['total_dps']:.2f}")
        lines.append(f"Total Cost: {result_dict['total_cost']:.2f}")
        lines.append("")
        
        for tower_data in result_dict['per_tower']:
            lines.append(f"- {tower_data['variant_name']}")
            lines.append(f"  DPS: {tower_data['dps']:.2f}")
            lines.append(f"  Damage: {tower_data['damage_final']:.2f}")
            lines.append(f"  Speed: {tower_data['speed_final']:.2f}")
            lines.append("")
        
        payload = "\n".join(lines)
        self.auto_text.configure(state="normal")
        self.auto_text.delete("1.0", tk.END)
        self.auto_text.insert(tk.END, payload)
        self.auto_text.configure(state="disabled")

    # ------------------------------------------------------------------ Helpers
    def _set_status(self, message: str) -> None:
        self.status_var.set(message)

    def _reset_autopick_progress(self) -> None:
        self.auto_progress["value"] = 0
        self.auto_progress["maximum"] = 1

    def _sort_tree(self, tree: ttk.Treeview, col: str, descending: bool) -> None:
        def convert(value: str):
            try:
                if col == "rank":
                    return int(value)
                if col in {"dps", "cost"}:
                    return float(value)
            except ValueError:
                pass
            return value.lower()

        data = [(convert(tree.set(item, col)), item) for item in tree.get_children("")]
        data.sort(reverse=descending)
        for index, (_, item) in enumerate(data):
            tree.move(item, "", index)
        tree.heading(col, command=lambda: self._sort_tree(tree, col, not descending))


def run_app() -> None:
    root = tk.Tk()
    NordholdApp(root)
    root.mainloop()
