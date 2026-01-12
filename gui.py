#!/usr/bin/env python
"""
🎬 Auto Video Editor - Interface Gráfica Moderna
Uma ferramenta poderosa para edição automática de vídeos com IA
"""

import os
import sys
import glob
import threading
import queue
from datetime import datetime

# Importações do CustomTkinter
import customtkinter as ctk
from tkinter import filedialog, messagebox
from PIL import Image

# Configurações do tema
ctk.set_appearance_mode("dark")
ctk.set_default_color_theme("blue")

# Carrega .env se existir
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass


class AutoVideoEditorGUI(ctk.CTk):
    """Interface gráfica principal do Auto Video Editor"""
    
    # Cores do tema
    COLORS = {
        "bg_dark": "#0d1117",
        "bg_card": "#161b22",
        "bg_secondary": "#21262d",
        "accent_primary": "#58a6ff",
        "accent_success": "#3fb950",
        "accent_warning": "#d29922",
        "accent_danger": "#f85149",
        "accent_purple": "#a371f7",
        "accent_pink": "#db61a2",
        "text_primary": "#f0f6fc",
        "text_secondary": "#8b949e",
        "border": "#30363d",
    }
    
    def __init__(self):
        super().__init__()
        
        # Configurações da janela
        self.title("🎬 Auto Video Editor")
        self.geometry("1400x900")
        self.minsize(1200, 800)
        
        # Configurar cor de fundo
        self.configure(fg_color=self.COLORS["bg_dark"])
        
        # Variáveis de estado
        self.selected_video = None
        self.is_processing = False
        self.log_queue = queue.Queue()
        self.api_key = os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY") or ""
        
        # Configurações padrão
        self.whisper_model = ctk.StringVar(value="small")
        self.cut_method = ctk.StringVar(value="speech")
        self.language = ctk.StringVar(value="pt")
        self.use_ai_correction = ctk.BooleanVar(value=True if self.api_key else False)
        
        # Criar interface
        self._create_layout()
        
        # Iniciar verificação de logs
        self._check_log_queue()
    
    def _create_layout(self):
        """Cria o layout principal da interface"""
        
        # Container principal com grid
        self.grid_columnconfigure(1, weight=1)
        self.grid_rowconfigure(0, weight=1)
        
        # Sidebar
        self._create_sidebar()
        
        # Área principal
        self._create_main_area()
    
    def _create_sidebar(self):
        """Cria a barra lateral com logo e navegação"""
        
        sidebar = ctk.CTkFrame(
            self,
            width=280,
            corner_radius=0,
            fg_color=self.COLORS["bg_card"],
            border_width=1,
            border_color=self.COLORS["border"]
        )
        sidebar.grid(row=0, column=0, sticky="nsew")
        sidebar.grid_propagate(False)
        
        # Logo e título
        logo_frame = ctk.CTkFrame(sidebar, fg_color="transparent")
        logo_frame.pack(fill="x", padx=20, pady=25)
        
        title_label = ctk.CTkLabel(
            logo_frame,
            text="🎬 Auto Video Editor",
            font=ctk.CTkFont(family="SF Pro Display", size=22, weight="bold"),
            text_color=self.COLORS["text_primary"]
        )
        title_label.pack(anchor="w")
        
        subtitle_label = ctk.CTkLabel(
            logo_frame,
            text="Edição inteligente com IA",
            font=ctk.CTkFont(family="SF Pro Text", size=13),
            text_color=self.COLORS["text_secondary"]
        )
        subtitle_label.pack(anchor="w", pady=(5, 0))
        
        # Separador
        separator = ctk.CTkFrame(sidebar, height=1, fg_color=self.COLORS["border"])
        separator.pack(fill="x", padx=20, pady=10)
        
        # Seção: Vídeo Selecionado
        section_label = ctk.CTkLabel(
            sidebar,
            text="📹 VÍDEO SELECIONADO",
            font=ctk.CTkFont(size=11, weight="bold"),
            text_color=self.COLORS["text_secondary"]
        )
        section_label.pack(anchor="w", padx=20, pady=(15, 10))
        
        self.video_label = ctk.CTkLabel(
            sidebar,
            text="Nenhum vídeo selecionado",
            font=ctk.CTkFont(size=13),
            text_color=self.COLORS["accent_warning"],
            wraplength=240
        )
        self.video_label.pack(anchor="w", padx=20, pady=(0, 15))
        
        # Separador
        separator2 = ctk.CTkFrame(sidebar, height=1, fg_color=self.COLORS["border"])
        separator2.pack(fill="x", padx=20, pady=10)
        
        # Seção: Configurações
        settings_label = ctk.CTkLabel(
            sidebar,
            text="⚙️ CONFIGURAÇÕES",
            font=ctk.CTkFont(size=11, weight="bold"),
            text_color=self.COLORS["text_secondary"]
        )
        settings_label.pack(anchor="w", padx=20, pady=(15, 10))
        
        # Modelo Whisper
        whisper_frame = ctk.CTkFrame(sidebar, fg_color="transparent")
        whisper_frame.pack(fill="x", padx=20, pady=5)
        
        ctk.CTkLabel(
            whisper_frame,
            text="Modelo Whisper:",
            font=ctk.CTkFont(size=12),
            text_color=self.COLORS["text_secondary"]
        ).pack(anchor="w")
        
        whisper_menu = ctk.CTkOptionMenu(
            whisper_frame,
            values=["tiny", "base", "small", "medium", "large"],
            variable=self.whisper_model,
            fg_color=self.COLORS["bg_secondary"],
            button_color=self.COLORS["accent_primary"],
            button_hover_color=self.COLORS["accent_purple"],
            dropdown_fg_color=self.COLORS["bg_secondary"]
        )
        whisper_menu.pack(fill="x", pady=(5, 0))
        
        # Método de corte
        cut_frame = ctk.CTkFrame(sidebar, fg_color="transparent")
        cut_frame.pack(fill="x", padx=20, pady=10)
        
        ctk.CTkLabel(
            cut_frame,
            text="Método de Corte:",
            font=ctk.CTkFont(size=12),
            text_color=self.COLORS["text_secondary"]
        ).pack(anchor="w")
        
        cut_menu = ctk.CTkOptionMenu(
            cut_frame,
            values=["speech", "volume"],
            variable=self.cut_method,
            fg_color=self.COLORS["bg_secondary"],
            button_color=self.COLORS["accent_primary"],
            button_hover_color=self.COLORS["accent_purple"],
            dropdown_fg_color=self.COLORS["bg_secondary"]
        )
        cut_menu.pack(fill="x", pady=(5, 0))
        
        # Idioma
        lang_frame = ctk.CTkFrame(sidebar, fg_color="transparent")
        lang_frame.pack(fill="x", padx=20, pady=10)
        
        ctk.CTkLabel(
            lang_frame,
            text="Idioma:",
            font=ctk.CTkFont(size=12),
            text_color=self.COLORS["text_secondary"]
        ).pack(anchor="w")
        
        lang_menu = ctk.CTkOptionMenu(
            lang_frame,
            values=["pt", "en", "es", "fr", "de", "it", "ja", "ko", "zh"],
            variable=self.language,
            fg_color=self.COLORS["bg_secondary"],
            button_color=self.COLORS["accent_primary"],
            button_hover_color=self.COLORS["accent_purple"],
            dropdown_fg_color=self.COLORS["bg_secondary"]
        )
        lang_menu.pack(fill="x", pady=(5, 0))
        
        # Correção IA
        ai_frame = ctk.CTkFrame(sidebar, fg_color="transparent")
        ai_frame.pack(fill="x", padx=20, pady=10)
        
        ai_switch = ctk.CTkSwitch(
            ai_frame,
            text="Correção com IA (Gemini)",
            variable=self.use_ai_correction,
            font=ctk.CTkFont(size=12),
            text_color=self.COLORS["text_secondary"],
            progress_color=self.COLORS["accent_success"],
            button_color=self.COLORS["text_primary"],
            button_hover_color=self.COLORS["accent_primary"]
        )
        ai_switch.pack(anchor="w")
        
        # Status da API Key
        api_status = "✅ Configurada" if self.api_key else "❌ Não configurada"
        api_color = self.COLORS["accent_success"] if self.api_key else self.COLORS["accent_danger"]
        
        self.api_label = ctk.CTkLabel(
            ai_frame,
            text=f"API Key: {api_status}",
            font=ctk.CTkFont(size=11),
            text_color=api_color
        )
        self.api_label.pack(anchor="w", pady=(5, 0))
        
        # Botão para configurar API
        if not self.api_key:
            api_btn = ctk.CTkButton(
                ai_frame,
                text="Configurar API Key",
                font=ctk.CTkFont(size=11),
                fg_color=self.COLORS["bg_secondary"],
                hover_color=self.COLORS["accent_primary"],
                height=28,
                command=self._configure_api_key
            )
            api_btn.pack(fill="x", pady=(5, 0))
        
        # Espaçador
        sidebar.pack_propagate(False)
        
        # Rodapé com versão
        footer_frame = ctk.CTkFrame(sidebar, fg_color="transparent")
        footer_frame.pack(side="bottom", fill="x", padx=20, pady=20)
        
        separator3 = ctk.CTkFrame(footer_frame, height=1, fg_color=self.COLORS["border"])
        separator3.pack(fill="x", pady=(0, 15))
        
        ctk.CTkLabel(
            footer_frame,
            text="v1.0.0 • Powered by Whisper & Gemini",
            font=ctk.CTkFont(size=10),
            text_color=self.COLORS["text_secondary"]
        ).pack()
    
    def _create_main_area(self):
        """Cria a área principal da interface"""
        
        main_frame = ctk.CTkFrame(
            self,
            fg_color=self.COLORS["bg_dark"],
            corner_radius=0
        )
        main_frame.grid(row=0, column=1, sticky="nsew", padx=0, pady=0)
        main_frame.grid_columnconfigure(0, weight=1)
        main_frame.grid_rowconfigure(1, weight=1)
        
        # Header
        self._create_header(main_frame)
        
        # Conteúdo principal (scrollable)
        content_scroll = ctk.CTkScrollableFrame(
            main_frame,
            fg_color="transparent",
            scrollbar_button_color=self.COLORS["bg_secondary"],
            scrollbar_button_hover_color=self.COLORS["accent_primary"]
        )
        content_scroll.grid(row=1, column=0, sticky="nsew", padx=30, pady=(0, 20))
        content_scroll.grid_columnconfigure(0, weight=1)
        
        # Área de drop do vídeo
        self._create_drop_zone(content_scroll)
        
        # Cards de ação
        self._create_action_cards(content_scroll)
        
        # Console de logs
        self._create_log_console(content_scroll)
    
    def _create_header(self, parent):
        """Cria o cabeçalho da área principal"""
        
        header = ctk.CTkFrame(parent, fg_color="transparent", height=80)
        header.grid(row=0, column=0, sticky="ew", padx=30, pady=20)
        header.grid_columnconfigure(0, weight=1)
        
        # Título da página
        page_title = ctk.CTkLabel(
            header,
            text="Dashboard de Edição",
            font=ctk.CTkFont(family="SF Pro Display", size=28, weight="bold"),
            text_color=self.COLORS["text_primary"]
        )
        page_title.grid(row=0, column=0, sticky="w")
        
        page_subtitle = ctk.CTkLabel(
            header,
            text="Selecione um vídeo e escolha a operação desejada",
            font=ctk.CTkFont(size=14),
            text_color=self.COLORS["text_secondary"]
        )
        page_subtitle.grid(row=1, column=0, sticky="w", pady=(5, 0))
        
        # Botão de ajuda
        help_btn = ctk.CTkButton(
            header,
            text="❓ Ajuda",
            font=ctk.CTkFont(size=12),
            fg_color=self.COLORS["bg_secondary"],
            hover_color=self.COLORS["border"],
            width=80,
            height=32,
            command=self._show_help
        )
        help_btn.grid(row=0, column=1, rowspan=2, sticky="e")
    
    def _create_drop_zone(self, parent):
        """Cria a zona de arrastar e soltar vídeos"""
        
        drop_frame = ctk.CTkFrame(
            parent,
            fg_color=self.COLORS["bg_card"],
            corner_radius=16,
            border_width=2,
            border_color=self.COLORS["border"]
        )
        drop_frame.grid(row=0, column=0, sticky="ew", pady=(0, 25))
        
        drop_inner = ctk.CTkFrame(
            drop_frame,
            fg_color="transparent",
            height=180
        )
        drop_inner.pack(fill="x", padx=30, pady=30)
        
        # Ícone grande
        icon_label = ctk.CTkLabel(
            drop_inner,
            text="🎥",
            font=ctk.CTkFont(size=60)
        )
        icon_label.pack(pady=(0, 15))
        
        # Texto principal
        main_text = ctk.CTkLabel(
            drop_inner,
            text="Clique para selecionar um vídeo",
            font=ctk.CTkFont(size=18, weight="bold"),
            text_color=self.COLORS["text_primary"]
        )
        main_text.pack()
        
        # Texto secundário
        sub_text = ctk.CTkLabel(
            drop_inner,
            text="Suporta MP4, MOV, MKV, AVI",
            font=ctk.CTkFont(size=13),
            text_color=self.COLORS["text_secondary"]
        )
        sub_text.pack(pady=(5, 15))
        
        # Botão de seleção
        select_btn = ctk.CTkButton(
            drop_inner,
            text="📂 Selecionar Vídeo",
            font=ctk.CTkFont(size=14, weight="bold"),
            fg_color=self.COLORS["accent_primary"],
            hover_color=self.COLORS["accent_purple"],
            height=45,
            width=200,
            corner_radius=10,
            command=self._select_video
        )
        select_btn.pack()
        
        # Tornar a área clicável
        drop_frame.bind("<Button-1>", lambda e: self._select_video())
        drop_inner.bind("<Button-1>", lambda e: self._select_video())
    
    def _create_action_cards(self, parent):
        """Cria os cards de ação"""
        
        # Título da seção
        section_title = ctk.CTkLabel(
            parent,
            text="🚀 Ações Disponíveis",
            font=ctk.CTkFont(size=18, weight="bold"),
            text_color=self.COLORS["text_primary"]
        )
        section_title.grid(row=1, column=0, sticky="w", pady=(0, 15))
        
        # Container dos cards
        cards_frame = ctk.CTkFrame(parent, fg_color="transparent")
        cards_frame.grid(row=2, column=0, sticky="ew", pady=(0, 25))
        cards_frame.grid_columnconfigure((0, 1, 2), weight=1, uniform="card")
        
        # Card 1: Remover Silêncio
        self._create_card(
            cards_frame,
            column=0,
            icon="✂️",
            title="Remover Silêncio",
            description="Detecta e remove automaticamente pausas e silêncios do vídeo",
            button_text="Executar Corte",
            button_color=self.COLORS["accent_danger"],
            button_hover=self.COLORS["accent_pink"],
            command=self._action_remove_silence
        )
        
        # Card 2: Gerar Legendas
        self._create_card(
            cards_frame,
            column=1,
            icon="📝",
            title="Gerar Legendas",
            description="Transcreve o áudio e adiciona legendas estilo CapCut (karaokê)",
            button_text="Gerar Legendas",
            button_color=self.COLORS["accent_success"],
            button_hover="#2ea043",
            command=self._action_add_subtitles
        )
        
        # Card 3: Processo Completo
        self._create_card(
            cards_frame,
            column=2,
            icon="⚡",
            title="Processo Completo",
            description="Pipeline completo: Corta silêncio + Adiciona legendas + Correção IA",
            button_text="Executar Tudo",
            button_color=self.COLORS["accent_purple"],
            button_hover=self.COLORS["accent_primary"],
            command=self._action_full_process
        )
    
    def _create_card(self, parent, column, icon, title, description, button_text, button_color, button_hover, command):
        """Cria um card de ação individual"""
        
        card = ctk.CTkFrame(
            parent,
            fg_color=self.COLORS["bg_card"],
            corner_radius=16,
            border_width=1,
            border_color=self.COLORS["border"]
        )
        card.grid(row=0, column=column, sticky="nsew", padx=8)
        
        # Conteúdo do card
        content = ctk.CTkFrame(card, fg_color="transparent")
        content.pack(fill="both", expand=True, padx=25, pady=25)
        
        # Ícone
        icon_frame = ctk.CTkFrame(
            content,
            width=60,
            height=60,
            corner_radius=15,
            fg_color=self.COLORS["bg_secondary"]
        )
        icon_frame.pack(anchor="w")
        icon_frame.pack_propagate(False)
        
        icon_label = ctk.CTkLabel(
            icon_frame,
            text=icon,
            font=ctk.CTkFont(size=28)
        )
        icon_label.place(relx=0.5, rely=0.5, anchor="center")
        
        # Título
        title_label = ctk.CTkLabel(
            content,
            text=title,
            font=ctk.CTkFont(size=17, weight="bold"),
            text_color=self.COLORS["text_primary"]
        )
        title_label.pack(anchor="w", pady=(15, 5))
        
        # Descrição
        desc_label = ctk.CTkLabel(
            content,
            text=description,
            font=ctk.CTkFont(size=12),
            text_color=self.COLORS["text_secondary"],
            wraplength=230,
            justify="left"
        )
        desc_label.pack(anchor="w", pady=(0, 20))
        
        # Botão de ação
        action_btn = ctk.CTkButton(
            content,
            text=button_text,
            font=ctk.CTkFont(size=13, weight="bold"),
            fg_color=button_color,
            hover_color=button_hover,
            height=42,
            corner_radius=10,
            command=command
        )
        action_btn.pack(fill="x")
    
    def _create_log_console(self, parent):
        """Cria o console de logs"""
        
        # Título da seção
        section_title = ctk.CTkLabel(
            parent,
            text="📋 Console de Processamento",
            font=ctk.CTkFont(size=18, weight="bold"),
            text_color=self.COLORS["text_primary"]
        )
        section_title.grid(row=3, column=0, sticky="w", pady=(10, 15))
        
        # Frame do console
        console_frame = ctk.CTkFrame(
            parent,
            fg_color=self.COLORS["bg_card"],
            corner_radius=16,
            border_width=1,
            border_color=self.COLORS["border"]
        )
        console_frame.grid(row=4, column=0, sticky="nsew", pady=(0, 10))
        
        # Barra de progresso
        self.progress_frame = ctk.CTkFrame(console_frame, fg_color="transparent")
        self.progress_frame.pack(fill="x", padx=20, pady=(20, 10))
        
        self.progress_label = ctk.CTkLabel(
            self.progress_frame,
            text="Aguardando início...",
            font=ctk.CTkFont(size=12),
            text_color=self.COLORS["text_secondary"]
        )
        self.progress_label.pack(anchor="w")
        
        self.progress_bar = ctk.CTkProgressBar(
            self.progress_frame,
            progress_color=self.COLORS["accent_primary"],
            fg_color=self.COLORS["bg_secondary"],
            height=8,
            corner_radius=4
        )
        self.progress_bar.pack(fill="x", pady=(8, 0))
        self.progress_bar.set(0)
        
        # Área de texto de logs
        self.log_text = ctk.CTkTextbox(
            console_frame,
            font=ctk.CTkFont(family="SF Mono", size=12),
            fg_color=self.COLORS["bg_secondary"],
            text_color=self.COLORS["text_primary"],
            height=200,
            corner_radius=10,
            border_width=0
        )
        self.log_text.pack(fill="both", expand=True, padx=20, pady=(10, 20))
        
        # Mensagem inicial
        self._add_log("Sistema inicializado. Pronto para processar vídeos.", "info")
    
    # ===================== MÉTODOS DE AÇÃO =====================
    
    def _select_video(self):
        """Abre diálogo para selecionar vídeo"""
        filetypes = [
            ("Arquivos de Vídeo", "*.mp4 *.MP4 *.mov *.MOV *.mkv *.MKV *.avi *.AVI"),
            ("Todos os arquivos", "*.*")
        ]
        
        filepath = filedialog.askopenfilename(
            title="Selecione um vídeo",
            filetypes=filetypes
        )
        
        if filepath:
            self.selected_video = filepath
            filename = os.path.basename(filepath)
            self.video_label.configure(
                text=f"✅ {filename}",
                text_color=self.COLORS["accent_success"]
            )
            self._add_log(f"Vídeo selecionado: {filename}", "success")
    
    def _configure_api_key(self):
        """Abre diálogo para configurar API key"""
        dialog = ctk.CTkInputDialog(
            text="Digite sua API Key do Google Gemini:",
            title="Configurar API Key"
        )
        key = dialog.get_input()
        
        if key:
            self.api_key = key
            os.environ["GEMINI_API_KEY"] = key
            self.api_label.configure(
                text="API Key: ✅ Configurada",
                text_color=self.COLORS["accent_success"]
            )
            self.use_ai_correction.set(True)
            self._add_log("API Key do Gemini configurada com sucesso!", "success")
    
    def _show_help(self):
        """Mostra diálogo de ajuda"""
        help_text = """
🎬 Auto Video Editor - Guia Rápido

📹 FUNCIONALIDADES:

1️⃣ REMOVER SILÊNCIO
   • Detecta pausas e silêncios automaticamente
   • Método "speech" usa IA (mais preciso)
   • Método "volume" usa detecção por dB (mais rápido)

2️⃣ GERAR LEGENDAS
   • Transcrição automática com Whisper
   • Legendas estilo CapCut (karaokê)
   • Destaque palavra a palavra

3️⃣ PROCESSO COMPLETO
   • Executa corte + legendas automaticamente
   • Opcional: Correção ortográfica com IA

⚙️ CONFIGURAÇÕES:

• Modelo Whisper: tiny (rápido) → large (preciso)
• Correção IA: Requer API Key do Google Gemini

💡 DICA: Para melhores resultados, use o
   modelo "small" ou "medium" para legendas.
        """
        messagebox.showinfo("Ajuda - Auto Video Editor", help_text)
    
    def _validate_video(self):
        """Valida se um vídeo foi selecionado"""
        if not self.selected_video:
            messagebox.showwarning(
                "Atenção",
                "Por favor, selecione um vídeo primeiro!"
            )
            return False
        
        if not os.path.isfile(self.selected_video):
            messagebox.showerror(
                "Erro",
                "O arquivo de vídeo não foi encontrado!"
            )
            return False
        
        return True
    
    def _action_remove_silence(self):
        """Executa ação de remover silêncio"""
        if not self._validate_video() or self.is_processing:
            return
        
        def process():
            try:
                self._add_log("Iniciando remoção de silêncio...", "info")
                self._update_progress("Carregando módulos de IA...", 0.1)
                
                from remove_silence import remover_silencio
                
                base, ext = os.path.splitext(self.selected_video)
                output_path = f"{base}_cut{ext}"
                
                self._update_progress("Analisando áudio...", 0.3)
                
                # Redirecionar stdout para capturar logs
                import io
                import contextlib
                
                success = remover_silencio(
                    self.selected_video,
                    output_path,
                    method=self.cut_method.get()
                )
                
                if success:
                    self._update_progress("Concluído!", 1.0)
                    self._add_log(f"✅ Vídeo cortado salvo em: {os.path.basename(output_path)}", "success")
                    messagebox.showinfo("Sucesso!", f"Vídeo processado e salvo em:\n{output_path}")
                else:
                    self._add_log("❌ Falha no processamento", "error")
                    
            except Exception as e:
                self._add_log(f"❌ Erro: {str(e)}", "error")
                messagebox.showerror("Erro", f"Erro durante o processamento:\n{str(e)}")
            finally:
                self.is_processing = False
                self._update_progress("Aguardando início...", 0)
        
        self.is_processing = True
        threading.Thread(target=process, daemon=True).start()
    
    def _action_add_subtitles(self):
        """Executa ação de adicionar legendas"""
        if not self._validate_video() or self.is_processing:
            return
        
        def process():
            try:
                self._add_log("Iniciando processo de legendagem...", "info")
                self._update_progress("Carregando Whisper...", 0.1)
                
                from auto_caption import processar_legenda_completo
                
                base, ext = os.path.splitext(self.selected_video)
                output_path = f"{base}_legendado{ext}"
                
                gemini_key = self.api_key if self.use_ai_correction.get() else None
                
                self._update_progress("Transcrevendo áudio...", 0.3)
                self._add_log(f"Usando modelo Whisper: {self.whisper_model.get()}", "info")
                
                processar_legenda_completo(
                    self.selected_video,
                    output_path,
                    model_name=self.whisper_model.get(),
                    language=self.language.get(),
                    gemini_key=gemini_key
                )
                
                self._update_progress("Concluído!", 1.0)
                self._add_log(f"✅ Vídeo legendado salvo em: {os.path.basename(output_path)}", "success")
                messagebox.showinfo("Sucesso!", f"Vídeo legendado salvo em:\n{output_path}")
                
            except Exception as e:
                self._add_log(f"❌ Erro: {str(e)}", "error")
                messagebox.showerror("Erro", f"Erro durante o processamento:\n{str(e)}")
            finally:
                self.is_processing = False
                self._update_progress("Aguardando início...", 0)
        
        self.is_processing = True
        threading.Thread(target=process, daemon=True).start()
    
    def _action_full_process(self):
        """Executa processo completo"""
        if not self._validate_video() or self.is_processing:
            return
        
        def process():
            try:
                self._add_log("🚀 Iniciando processo completo...", "info")
                self._update_progress("Carregando módulos...", 0.05)
                
                from remove_silence import remover_silencio
                from auto_caption import processar_legenda_completo
                
                base, ext = os.path.splitext(self.selected_video)
                
                # Passo 1: Cortar silêncio
                self._add_log("📌 Passo 1/2: Removendo silêncio...", "info")
                self._update_progress("Analisando áudio...", 0.2)
                
                cut_path = f"{base}_cut{ext}"
                success = remover_silencio(
                    self.selected_video,
                    cut_path,
                    method=self.cut_method.get()
                )
                
                video_to_caption = cut_path if success else self.selected_video
                
                # Passo 2: Legendar
                self._add_log("📌 Passo 2/2: Gerando legendas...", "info")
                self._update_progress("Transcrevendo com Whisper...", 0.5)
                
                final_path = f"{base}_final{ext}"
                gemini_key = self.api_key if self.use_ai_correction.get() else None
                
                processar_legenda_completo(
                    video_to_caption,
                    final_path,
                    model_name=self.whisper_model.get(),
                    language=self.language.get(),
                    gemini_key=gemini_key
                )
                
                self._update_progress("Concluído!", 1.0)
                self._add_log(f"✅ Processo completo! Salvo em: {os.path.basename(final_path)}", "success")
                messagebox.showinfo("Sucesso!", f"Processo completo!\nVídeo final salvo em:\n{final_path}")
                
            except Exception as e:
                self._add_log(f"❌ Erro: {str(e)}", "error")
                messagebox.showerror("Erro", f"Erro durante o processamento:\n{str(e)}")
            finally:
                self.is_processing = False
                self._update_progress("Aguardando início...", 0)
        
        self.is_processing = True
        threading.Thread(target=process, daemon=True).start()
    
    # ===================== MÉTODOS AUXILIARES =====================
    
    def _add_log(self, message, level="info"):
        """Adiciona mensagem ao log de forma thread-safe"""
        self.log_queue.put((message, level))
    
    def _update_progress(self, text, value):
        """Atualiza barra de progresso de forma thread-safe"""
        self.log_queue.put(("__progress__", (text, value)))
    
    def _check_log_queue(self):
        """Verifica a fila de logs e atualiza a interface"""
        try:
            while True:
                item = self.log_queue.get_nowait()
                
                if item[0] == "__progress__":
                    text, value = item[1]
                    self.progress_label.configure(text=text)
                    self.progress_bar.set(value)
                else:
                    message, level = item
                    timestamp = datetime.now().strftime("%H:%M:%S")
                    
                    # Cores por nível
                    prefix = {
                        "info": "ℹ️",
                        "success": "✅",
                        "warning": "⚠️",
                        "error": "❌"
                    }.get(level, "•")
                    
                    self.log_text.insert("end", f"[{timestamp}] {prefix} {message}\n")
                    self.log_text.see("end")
                    
        except queue.Empty:
            pass
        
        # Reagendar verificação
        self.after(100, self._check_log_queue)


def main():
    """Função principal para iniciar a aplicação"""
    app = AutoVideoEditorGUI()
    app.mainloop()


if __name__ == "__main__":
    main()

