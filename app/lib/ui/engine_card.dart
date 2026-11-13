import 'package:auto_edit_client/auto_edit_client.dart';
import 'package:flutter/material.dart';

import '../engine/status.dart';
import 'theme.dart';

/// Which engine the app talks to: address, version, contract (end of Configurações).
class EngineCard extends StatelessWidget {
  const EngineCard({super.key, required this.status, required this.client});

  final EngineStatus status;
  final AutoEditClient client;

  @override
  Widget build(BuildContext context) => ListenableBuilder(
    listenable: status,
    builder: (context, _) {
      final health = status.info;
      return _Card(
        title: 'Motor',
        rows: [
          ('Endereço', client.config.baseUrl.toString()),
          ('Versão', health?.version ?? '—'),
          ('Contrato da API', health == null ? '—' : '${health.apiVersion} (este app: ${AutoEditApi.contractVersion})'),
          if (health?.repoRoot != null) ('Pasta do motor', health!.repoRoot!),
        ],
        footer: health != null && health.apiVersion.split('.').first != AutoEditApi.contractVersion.split('.').first
            ? 'Este motor fala outra versão do contrato. Atualize o app ou o motor.'
            : null,
      );
    },
  );
}

class _Card extends StatelessWidget {
  const _Card({required this.title, required this.rows, this.footer});

  final String title;
  final List<(String, String)> rows;
  final String? footer;

  @override
  Widget build(BuildContext context) {
    return Container(
      padding: const EdgeInsets.all(20),
      decoration: BoxDecoration(
        color: Tokens.panel,
        border: Border.all(color: Tokens.border),
        borderRadius: BorderRadius.circular(14),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Text(title, style: const TextStyle(fontSize: 15, fontWeight: FontWeight.w600)),
          const SizedBox(height: 14),
          for (final (label, value) in rows)
            Padding(
              padding: const EdgeInsets.only(bottom: 8),
              child: Row(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  SizedBox(
                    width: 150,
                    child: Text(label, style: const TextStyle(fontSize: 13, color: Tokens.dim)),
                  ),
                  Expanded(
                    child: SelectableText(value, style: const TextStyle(fontFamily: Tokens.mono, fontSize: 12.5)),
                  ),
                ],
              ),
            ),
          if (footer != null) Text(footer!, style: const TextStyle(fontSize: 13, color: Tokens.err)),
        ],
      ),
    );
  }
}
