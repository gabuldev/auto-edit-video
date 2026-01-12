import 'dart:io';

import 'package:flutter_dotenv/flutter_dotenv.dart';
import 'package:path/path.dart' as p;

class VideoProcessor {
  // Busca do .env ou usa fallback
  static String get _pythonScriptPath {
    final corePath = dotenv.env['PYTHON_CORE_PATH'];
    if (corePath != null) {
      return p.join(corePath, 'api_cli.py');
    }
    // Fallback original (funciona em alguns ambientes não sandboxed)
    return p.join(Directory.current.parent.path, 'python_core', 'api_cli.py');
  }

  static String get _pythonExecutable {
    return dotenv.env['PYTHON_INTERPRETER_PATH'] ?? 'python3';
  }

  /// Executa o script CLI Python para processar o vídeo.
  /// [command] pode ser 'remove-silence', 'auto-caption', etc.
  static Future<String> runCommand(String command, List<String> args) async {
    // Verifica se o script existe
    if (!File(_pythonScriptPath).existsSync()) {
      throw Exception("Python CLI script not found at: $_pythonScriptPath");
    }

    // Monta os argumentos: python3 cli.py <command> <args>
    final processArgs = [_pythonScriptPath, command, ...args];

    print("Executing: $_pythonExecutable ${processArgs.join(' ')}");

    try {
      final result = await Process.run(
        _pythonExecutable,
        processArgs,
        runInShell: true,
      );

      if (result.exitCode != 0) {
        throw Exception("Python Script Error: ${result.stderr}");
      }

      return result.stdout.toString();
    } catch (e) {
      throw Exception("Failed to execute python script: $e");
    }
  }

  static Future<String> removeSilence(
    String videoPath, {
    double threshold = -40.0,
  }) async {
    return runCommand('remove-silence', [
      '--file',
      videoPath,
      '--threshold',
      threshold.toString(),
    ]);
  }

  static Future<String> autoCaption(String videoPath) async {
    return runCommand('auto-caption', ['--file', videoPath]);
  }
}
