import 'package:dartantic_ai/dartantic_ai.dart';
import 'package:desktop_drop/desktop_drop.dart';
import 'package:file_picker/file_picker.dart';
import 'package:flutter/material.dart';
import 'package:flutter_dotenv/flutter_dotenv.dart';
import 'package:google_fonts/google_fonts.dart';

import 'services/video_processor.dart';

Future<void> main() async {
  await dotenv.load(fileName: ".env");
  runApp(const MyApp());
}

class MyApp extends StatelessWidget {
  const MyApp({super.key});

  @override
  Widget build(BuildContext context) {
    return MaterialApp(
      title: 'Auto Edit Video GUI',
      debugShowCheckedModeBanner: false,
      theme: ThemeData(
        colorScheme: ColorScheme.fromSeed(seedColor: Colors.deepPurple),
        useMaterial3: true,
        textTheme: GoogleFonts.interTextTheme(),
      ),
      home: const ChatScreen(),
    );
  }
}

class ChatScreen extends StatefulWidget {
  const ChatScreen({super.key});

  @override
  State<ChatScreen> createState() => _ChatScreenState();
}

class _ChatScreenState extends State<ChatScreen> {
  final TextEditingController _controller = TextEditingController();
  final ScrollController _scrollController = ScrollController();
  final List<Map<String, String>> _messages = [];
  bool _isLoading = false;
  String? _selectedVideoPath;
  bool _isDragging = false;

  late final Agent _agent;

  @override
  void initState() {
    super.initState();
    _agent = Agent('ollama:deepseek-r1:8b');
  }

  void _scrollToBottom() {
    WidgetsBinding.instance.addPostFrameCallback((_) {
      if (_scrollController.hasClients) {
        _scrollController.animateTo(
          _scrollController.position.maxScrollExtent,
          duration: const Duration(milliseconds: 300),
          curve: Curves.easeOut,
        );
      }
    });
  }

  Future<void> _pickVideo() async {
    FilePickerResult? result = await FilePicker.platform.pickFiles(
      type: FileType.video,
    );

    if (result != null) {
      _setVideo(result.files.single.path!);
    }
  }

  void _setVideo(String path) {
    setState(() {
      _selectedVideoPath = path;
      _messages.add({
        "role": "system",
        "content": "Vídeo selecionado: $_selectedVideoPath",
      });
    });
    _scrollToBottom();
  }

  Future<void> _processVideo() async {
    if (_selectedVideoPath == null) return;

    setState(() {
      _isLoading = true;
      _messages.add({
        "role": "system",
        "content": "Iniciando processamento (Remover Silêncio)...",
      });
    });

    try {
      final output = await VideoProcessor.removeSilence(_selectedVideoPath!);

      setState(() {
        _messages.add({
          "role": "system",
          "content": "Resultado Python:\n$output",
        });
      });
    } catch (e) {
      setState(() {
        _messages.add({"role": "error", "content": "Erro ao processar: $e"});
      });
    } finally {
      setState(() {
        _isLoading = false;
      });
      _scrollToBottom();
    }
  }

  Future<void> _sendMessage() async {
    if (_controller.text.isEmpty) return;

    final userMessage = _controller.text;
    setState(() {
      _messages.add({"role": "user", "content": userMessage});
      _isLoading = true;
    });
    _controller.clear();
    _scrollToBottom();

    try {
      final response = await _agent.send(userMessage);
      setState(() {
        _messages.add({"role": "ai", "content": response.output});
      });
    } catch (e) {
      setState(() {
        _messages.add({"role": "error", "content": "Erro na IA: $e"});
      });
    } finally {
      setState(() {
        _isLoading = false;
      });
      _scrollToBottom();
    }
  }

  @override
  Widget build(BuildContext context) {
    return DropTarget(
      onDragDone: (detail) {
        if (detail.files.isNotEmpty) {
          final file = detail.files.first;
          // Verifica extensão simples
          if (file.path.toLowerCase().endsWith('.mp4') ||
              file.path.toLowerCase().endsWith('.mov') ||
              file.path.toLowerCase().endsWith('.mkv')) {
            _setVideo(file.path);
          }
        }
      },
      onDragEntered: (detail) {
        setState(() {
          _isDragging = true;
        });
      },
      onDragExited: (detail) {
        setState(() {
          _isDragging = false;
        });
      },
      child: Scaffold(
        appBar: AppBar(
          title: const Text('Auto Edit Video Agent'),
          backgroundColor: Theme.of(context).colorScheme.inversePrimary,
          actions: [
            IconButton(
              icon: const Icon(Icons.video_library),
              tooltip: "Selecionar Vídeo",
              onPressed: _pickVideo,
            ),
          ],
        ),
        body: Stack(
          children: [
            Column(
              children: [
                if (_selectedVideoPath != null)
                  Container(
                    padding: const EdgeInsets.all(8),
                    color: Colors.grey.shade100,
                    child: Row(
                      children: [
                        const Icon(
                          Icons.movie_creation,
                          color: Colors.deepPurple,
                        ),
                        const SizedBox(width: 8),
                        Expanded(
                          child: Text(
                            _selectedVideoPath!,
                            overflow: TextOverflow.ellipsis,
                            style: const TextStyle(fontSize: 12),
                          ),
                        ),
                        ElevatedButton.icon(
                          onPressed: _isLoading ? null : _processVideo,
                          icon: const Icon(Icons.cut, size: 16),
                          label: const Text("Cortar Silêncio"),
                        ),
                      ],
                    ),
                  ),
                Expanded(
                  child: ListView.builder(
                    controller: _scrollController,
                    padding: const EdgeInsets.all(16),
                    itemCount: _messages.length,
                    itemBuilder: (context, index) {
                      final msg = _messages[index];
                      final role = msg['role'];
                      final content = msg['content']!;

                      Color bgColor;
                      CrossAxisAlignment align;

                      if (role == 'user') {
                        bgColor = Theme.of(
                          context,
                        ).colorScheme.primaryContainer;
                        align = CrossAxisAlignment.end;
                      } else if (role == 'ai') {
                        bgColor = Theme.of(
                          context,
                        ).colorScheme.surfaceContainerHighest;
                        align = CrossAxisAlignment.start;
                      } else if (role == 'error') {
                        bgColor = Colors.red.shade100;
                        align = CrossAxisAlignment.center;
                      } else {
                        // System
                        bgColor = Colors.yellow.shade100;
                        align = CrossAxisAlignment.center;
                      }

                      return Align(
                        alignment: align == CrossAxisAlignment.center
                            ? Alignment.center
                            : (role == 'user'
                                  ? Alignment.centerRight
                                  : Alignment.centerLeft),
                        child: Container(
                          margin: const EdgeInsets.symmetric(vertical: 4),
                          padding: const EdgeInsets.all(12),
                          constraints: BoxConstraints(
                            maxWidth: MediaQuery.of(context).size.width * 0.8,
                          ),
                          decoration: BoxDecoration(
                            color: bgColor,
                            borderRadius: BorderRadius.circular(12),
                          ),
                          child: SelectableText(content),
                        ),
                      );
                    },
                  ),
                ),
                if (_isLoading) const LinearProgressIndicator(),
                Padding(
                  padding: const EdgeInsets.all(16.0),
                  child: Row(
                    children: [
                      Expanded(
                        child: TextField(
                          controller: _controller,
                          enabled: !_isLoading,
                          decoration: const InputDecoration(
                            hintText: 'Converse com o agente...',
                            border: OutlineInputBorder(),
                          ),
                          onSubmitted: (_) => _sendMessage(),
                        ),
                      ),
                      const SizedBox(width: 8),
                      IconButton(
                        onPressed: _isLoading ? null : _sendMessage,
                        icon: const Icon(Icons.send),
                        style: IconButton.styleFrom(
                          backgroundColor: Theme.of(
                            context,
                          ).colorScheme.primary,
                          foregroundColor: Theme.of(
                            context,
                          ).colorScheme.onPrimary,
                        ),
                      ),
                    ],
                  ),
                ),
              ],
            ),
            if (_isDragging)
              Container(
                color: Colors.black54,
                child: Center(
                  child: Column(
                    mainAxisSize: MainAxisSize.min,
                    children: [
                      const Icon(
                        Icons.cloud_upload,
                        size: 100,
                        color: Colors.white,
                      ),
                      const SizedBox(height: 20),
                      Text(
                        "Solte o arquivo de vídeo aqui",
                        style: GoogleFonts.inter(
                          fontSize: 24,
                          color: Colors.white,
                        ),
                      ),
                    ],
                  ),
                ),
              ),
          ],
        ),
      ),
    );
  }
}
