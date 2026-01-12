"""
🗄️ Database - Armazenamento local com SQLite
Gerencia logs, configurações e histórico de processamentos.
"""

import sqlite3
import os
import json
from datetime import datetime
from pathlib import Path
from contextlib import contextmanager

# Caminho do banco de dados (na pasta do projeto)
DB_PATH = Path(__file__).parent / "data.db"


@contextmanager
def get_db():
    """Context manager para conexão com o banco"""
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row  # Permite acesso por nome de coluna
    try:
        yield conn
        conn.commit()
    except Exception as e:
        conn.rollback()
        raise e
    finally:
        conn.close()


def init_db():
    """Inicializa o banco de dados com as tabelas necessárias"""
    with get_db() as conn:
        cursor = conn.cursor()
        
        # Tabela de configurações (chave/valor)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS settings (
                key TEXT PRIMARY KEY,
                value TEXT,
                updated_at TEXT DEFAULT CURRENT_TIMESTAMP
            )
        """)
        
        # Tabela de logs de processamento
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS process_logs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp TEXT DEFAULT CURRENT_TIMESTAMP,
                video_name TEXT,
                action TEXT,
                status TEXT,
                details TEXT,
                duration_seconds REAL
            )
        """)
        
        # Tabela de histórico de vídeos processados
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS video_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp TEXT DEFAULT CURRENT_TIMESTAMP,
                input_file TEXT,
                output_file TEXT,
                action TEXT,
                success INTEGER,
                file_size_mb REAL
            )
        """)
        
        # Inserir configurações padrão se não existirem
        defaults = {
            'workspace_dir': '.',
            'whisper_model': 'small',
            'cut_method': 'speech',
            'language': 'pt',
            'use_ai_correction': 'true',
            'gemini_api_key': ''
        }
        
        for key, value in defaults.items():
            cursor.execute("""
                INSERT OR IGNORE INTO settings (key, value) VALUES (?, ?)
            """, (key, value))
        
        print("✅ Banco de dados inicializado:", DB_PATH)


# ==================== CONFIGURAÇÕES ====================

def get_setting(key: str, default: str = None) -> str:
    """Obtém uma configuração do banco"""
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT value FROM settings WHERE key = ?", (key,))
        row = cursor.fetchone()
        return row['value'] if row else default


def set_setting(key: str, value: str):
    """Salva uma configuração no banco"""
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            INSERT OR REPLACE INTO settings (key, value, updated_at) 
            VALUES (?, ?, ?)
        """, (key, value, datetime.now().isoformat()))


def get_all_settings() -> dict:
    """Retorna todas as configurações como dicionário"""
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT key, value FROM settings")
        return {row['key']: row['value'] for row in cursor.fetchall()}


def update_settings(settings: dict):
    """Atualiza múltiplas configurações de uma vez"""
    for key, value in settings.items():
        set_setting(key, str(value))


# ==================== LOGS ====================

def add_log(video_name: str, action: str, status: str, details: str = "", duration: float = None):
    """Adiciona um registro de log"""
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            INSERT INTO process_logs (video_name, action, status, details, duration_seconds)
            VALUES (?, ?, ?, ?, ?)
        """, (video_name, action, status, details, duration))


def get_logs(limit: int = 50) -> list:
    """Retorna os últimos logs"""
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT * FROM process_logs 
            ORDER BY timestamp DESC 
            LIMIT ?
        """, (limit,))
        return [dict(row) for row in cursor.fetchall()]


def clear_logs():
    """Limpa todos os logs"""
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("DELETE FROM process_logs")


# ==================== HISTÓRICO DE VÍDEOS ====================

def add_video_history(input_file: str, output_file: str, action: str, success: bool, file_size_mb: float = None):
    """Adiciona um vídeo ao histórico"""
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            INSERT INTO video_history (input_file, output_file, action, success, file_size_mb)
            VALUES (?, ?, ?, ?, ?)
        """, (input_file, output_file, action, 1 if success else 0, file_size_mb))


def get_video_history(limit: int = 20) -> list:
    """Retorna o histórico de vídeos processados"""
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT * FROM video_history 
            ORDER BY timestamp DESC 
            LIMIT ?
        """, (limit,))
        return [dict(row) for row in cursor.fetchall()]


def get_stats() -> dict:
    """Retorna estatísticas de uso"""
    with get_db() as conn:
        cursor = conn.cursor()
        
        # Total de vídeos processados
        cursor.execute("SELECT COUNT(*) as total FROM video_history")
        total = cursor.fetchone()['total']
        
        # Vídeos com sucesso
        cursor.execute("SELECT COUNT(*) as success FROM video_history WHERE success = 1")
        success = cursor.fetchone()['success']
        
        # Por tipo de ação
        cursor.execute("""
            SELECT action, COUNT(*) as count 
            FROM video_history 
            GROUP BY action
        """)
        by_action = {row['action']: row['count'] for row in cursor.fetchall()}
        
        return {
            'total_processed': total,
            'successful': success,
            'failed': total - success,
            'by_action': by_action
        }


# ==================== INICIALIZAÇÃO ====================

# Inicializa o banco quando o módulo é importado
if not DB_PATH.exists():
    init_db()

