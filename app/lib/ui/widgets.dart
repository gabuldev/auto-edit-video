import 'package:auto_edit_client/auto_edit_client.dart';
import 'package:flutter/gestures.dart';
import 'package:flutter/material.dart';

import 'theme.dart';

/// The `.card` of the Tauri app: a titled panel.
class Panel extends StatelessWidget {
  const Panel({super.key, this.title, this.subtitle, this.leading, this.trailing, required this.children});

  final String? title;

  /// Text, or a [Text.rich] for the bold bits.
  final Widget? subtitle;
  final Widget? leading;
  final Widget? trailing;
  final List<Widget> children;

  @override
  Widget build(BuildContext context) {
    // A Material (not a decorated box) so the tiles and buttons inside it show their ink.
    return Padding(
      padding: const EdgeInsets.only(bottom: 18),
      child: Material(
        color: Tokens.panel,
        shape: RoundedRectangleBorder(
          side: const BorderSide(color: Tokens.border),
          borderRadius: BorderRadius.circular(14),
        ),
        child: Padding(
          padding: const EdgeInsets.all(20),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.stretch,
            children: [
              if (title != null)
                Padding(
                  padding: const EdgeInsets.only(bottom: 14),
                  child: Row(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      if (leading != null) ...[leading!, const SizedBox(width: 12)],
                      Expanded(
                        child: Column(
                          crossAxisAlignment: CrossAxisAlignment.start,
                          children: [
                            Text(title!, style: const TextStyle(fontSize: 16, fontWeight: FontWeight.w600)),
                            if (subtitle != null)
                              Padding(
                                padding: const EdgeInsets.only(top: 4),
                                child: DefaultTextStyle.merge(
                                  style: const TextStyle(fontSize: 13, color: Tokens.dim, height: 1.45),
                                  child: subtitle!,
                                ),
                              ),
                          ],
                        ),
                      ),
                      if (trailing != null) ...[const SizedBox(width: 12), trailing!],
                    ],
                  ),
                ),
              ...children,
            ],
          ),
        ),
      ),
    );
  }
}

/// A screen of forms: top bar, then a centered, scrolling column.
class FormScreen extends StatelessWidget {
  const FormScreen({super.key, this.top, required this.children, this.maxWidth = 760});

  final Widget? top;
  final List<Widget> children;
  final double maxWidth;

  @override
  Widget build(BuildContext context) => Column(
    crossAxisAlignment: CrossAxisAlignment.stretch,
    children: [
      ?top,
      Expanded(
        child: SingleChildScrollView(
          padding: const EdgeInsets.fromLTRB(28, 24, 28, 40),
          child: Align(
            alignment: Alignment.topCenter,
            child: ConstrainedBox(
              constraints: BoxConstraints(maxWidth: maxWidth),
              child: Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: children),
            ),
          ),
        ),
      ),
    ],
  );
}

enum Tone { err, ok, info, warn }

/// The `.banner`: an error (or a note) across the screen.
class Notice extends StatelessWidget {
  const Notice(this.text, {super.key, this.tone = Tone.err, this.action});

  final String text;
  final Tone tone;
  final Widget? action;

  @override
  Widget build(BuildContext context) {
    final color = switch (tone) {
      Tone.err => Tokens.err,
      Tone.ok => Tokens.ok,
      Tone.info => Tokens.info,
      Tone.warn => Tokens.run,
    };
    return Container(
      margin: const EdgeInsets.only(bottom: 14),
      padding: const EdgeInsets.symmetric(horizontal: 14, vertical: 10),
      decoration: BoxDecoration(
        color: color.withValues(alpha: .08),
        border: Border.all(color: color.withValues(alpha: .3)),
        borderRadius: BorderRadius.circular(10),
      ),
      child: Row(
        children: [
          Expanded(
            child: SelectableText(
              text,
              style: TextStyle(fontSize: 13, height: 1.45, color: Color.lerp(color, Colors.white, .45)),
            ),
          ),
          if (action != null) ...[const SizedBox(width: 12), action!],
        ],
      ),
    );
  }
}

/// `pronto` / `pendente` on the right of a welcome step.
class StatePill extends StatelessWidget {
  const StatePill(this.text, {super.key, required this.ok});
  final String text;
  final bool ok;

  @override
  Widget build(BuildContext context) {
    final color = ok ? Tokens.ok : Tokens.faint;
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 3),
      decoration: BoxDecoration(
        border: Border.all(color: color.withValues(alpha: .5)),
        borderRadius: BorderRadius.circular(99),
      ),
      child: Text(
        text,
        style: TextStyle(fontSize: 11.5, color: color, fontFamily: Tokens.mono),
      ),
    );
  }
}

/// The small `.badge` next to an agent's name (recomendado, principal, fallback).
class Badge2 extends StatelessWidget {
  const Badge2(this.text, {super.key, this.color = Tokens.accent});
  final String text;
  final Color color;

  @override
  Widget build(BuildContext context) => Container(
    margin: const EdgeInsets.only(left: 8),
    padding: const EdgeInsets.symmetric(horizontal: 7, vertical: 1),
    decoration: BoxDecoration(color: color.withValues(alpha: .14), borderRadius: BorderRadius.circular(6)),
    child: Text(
      text,
      style: TextStyle(fontSize: 10.5, color: color, fontWeight: FontWeight.w600),
    ),
  );
}

/// A link inside a sentence (`TextSpan`), in the accent color.
TextSpan link(String text, VoidCallback onTap) => TextSpan(
  text: text,
  style: const TextStyle(color: Tokens.accent),
  mouseCursor: SystemMouseCursors.click,
  recognizer: TapGestureRecognizer()..onTap = onTap,
);

/// `.btn-sm`: the outlined (or, [primary], filled) small button of the rows.
class SmallButton extends StatelessWidget {
  const SmallButton(this.label, {super.key, this.onPressed, this.primary = false});

  final String label;
  final VoidCallback? onPressed;
  final bool primary;

  @override
  Widget build(BuildContext context) {
    const style = ButtonStyle(
      visualDensity: VisualDensity.compact,
      padding: WidgetStatePropertyAll(EdgeInsets.symmetric(horizontal: 12)),
      textStyle: WidgetStatePropertyAll(
        TextStyle(fontSize: 12.5, fontFamily: Tokens.font, fontWeight: FontWeight.w600),
      ),
    );
    return primary
        ? FilledButton(style: style, onPressed: onPressed, child: Text(label))
        : OutlinedButton(style: style, onPressed: onPressed, child: Text(label));
  }
}

/// A red outlined button; [confirm] fills it (the second click of "are you sure?").
class DangerButton extends StatelessWidget {
  const DangerButton(this.label, {super.key, required this.onPressed, this.confirm = false, this.icon});
  final String label;
  final VoidCallback? onPressed;
  final bool confirm;
  final IconData? icon;

  @override
  Widget build(BuildContext context) {
    final style = ButtonStyle(
      visualDensity: VisualDensity.compact,
      padding: const WidgetStatePropertyAll(EdgeInsets.symmetric(horizontal: 12)),
      foregroundColor: WidgetStatePropertyAll(confirm ? Colors.white : Tokens.err),
      backgroundColor: WidgetStatePropertyAll(confirm ? Tokens.err.withValues(alpha: .85) : null),
      side: WidgetStatePropertyAll(BorderSide(color: Tokens.err.withValues(alpha: .5))),
      textStyle: const WidgetStatePropertyAll(
        TextStyle(fontSize: 12.5, fontFamily: Tokens.font, fontWeight: FontWeight.w600),
      ),
    );
    return icon == null
        ? OutlinedButton(style: style, onPressed: onPressed, child: Text(label))
        : OutlinedButton.icon(style: style, onPressed: onPressed, icon: Icon(icon, size: 16), label: Text(label));
  }
}

/// The dim line under an agent's name.
class Meta extends StatelessWidget {
  const Meta(this.text, {super.key, this.bad = false});
  final String text;
  final bool bad;

  @override
  Widget build(BuildContext context) =>
      Text(text, style: TextStyle(fontSize: 12, height: 1.45, color: bad ? const Color(0xFFE59A9A) : Tokens.faint));
}

InputDecoration fieldDecoration({String? hint}) => InputDecoration(
  hintText: hint,
  isDense: true,
  hintStyle: const TextStyle(color: Tokens.faint, fontSize: 12.5),
  contentPadding: const EdgeInsets.symmetric(horizontal: 12, vertical: 11),
  filled: true,
  fillColor: Tokens.panel2,
  border: OutlineInputBorder(
    borderRadius: BorderRadius.circular(9),
    borderSide: const BorderSide(color: Tokens.border),
  ),
  enabledBorder: OutlineInputBorder(
    borderRadius: BorderRadius.circular(9),
    borderSide: const BorderSide(color: Tokens.border),
  ),
  focusedBorder: OutlineInputBorder(
    borderRadius: BorderRadius.circular(9),
    borderSide: const BorderSide(color: Tokens.accent),
  ),
);

/// A message from an API failure, as the Tauri app shows `err.message`.
String errorText(Object e) => e is ApiException ? e.message : '$e';

/// The status `.chip`: a dot and a word, in the status color.
class Chip2 extends StatelessWidget {
  const Chip2(this.text, {super.key, required this.color, this.onTap});
  final String text;
  final Color color;
  final VoidCallback? onTap;

  @override
  Widget build(BuildContext context) {
    final chip = Container(
      padding: const EdgeInsets.symmetric(horizontal: 9, vertical: 3),
      decoration: BoxDecoration(color: color.withValues(alpha: .1), borderRadius: BorderRadius.circular(99)),
      child: Row(
        mainAxisSize: MainAxisSize.min,
        children: [
          Container(
            width: 6,
            height: 6,
            decoration: BoxDecoration(color: color, shape: BoxShape.circle),
          ),
          const SizedBox(width: 6),
          Flexible(
            child: Text(
              text,
              maxLines: 1,
              overflow: TextOverflow.ellipsis,
              style: TextStyle(fontSize: 12, color: color, fontWeight: FontWeight.w500),
            ),
          ),
        ],
      ),
    );
    return onTap == null ? chip : InkWell(borderRadius: BorderRadius.circular(99), onTap: onTap, child: chip);
  }
}

/// `short` / `long`.
class TypeBadge extends StatelessWidget {
  const TypeBadge(this.type, {super.key});
  final VideoType type;

  @override
  Widget build(BuildContext context) =>
      Badge2(type.value, color: type == VideoType.short ? const Color(0xFFC084FC) : Tokens.accent);
}

/// A video's picture (16:9, rounded) from the engine; a blank tile without one.
class VideoThumb extends StatelessWidget {
  const VideoThumb({super.key, this.url, this.headers = const {}, this.width = 96});
  final Uri? url;
  final Map<String, String> headers;
  final double width;

  @override
  Widget build(BuildContext context) {
    final blank = Container(color: Tokens.panel2);
    return ClipRRect(
      borderRadius: BorderRadius.circular(7),
      child: SizedBox(
        width: width,
        height: width * 9 / 16,
        child: url == null
            ? blank
            : Image.network(
                url.toString(),
                headers: headers,
                fit: BoxFit.cover,
                errorBuilder: (_, _, _) => blank,
                frameBuilder: (_, child, frame, sync) => frame == null && !sync ? blank : child,
              ),
      ),
    );
  }
}
