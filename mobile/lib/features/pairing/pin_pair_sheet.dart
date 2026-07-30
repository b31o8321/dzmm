import 'package:flutter/material.dart';
import 'package:flutter/services.dart';

class PinPairSheet extends StatefulWidget {
  const PinPairSheet({super.key});

  @override
  State<PinPairSheet> createState() => _PinPairSheetState();
}

class _PinPairSheetState extends State<PinPairSheet> {
  final _controller = TextEditingController();

  @override
  void dispose() {
    _controller.dispose();
    super.dispose();
  }

  void _submit() {
    if (_controller.text.length == 6) {
      Navigator.of(context).pop(_controller.text);
    }
  }

  @override
  Widget build(BuildContext context) {
    return SafeArea(
      child: Padding(
        padding: EdgeInsets.fromLTRB(
          24,
          20,
          24,
          20 + MediaQuery.viewInsetsOf(context).bottom,
        ),
        child: Column(
          mainAxisSize: MainAxisSize.min,
          crossAxisAlignment: CrossAxisAlignment.stretch,
          children: [
            Text(
              '输入 Mac 上的 PIN',
              style: Theme.of(context).textTheme.titleLarge,
            ),
            const SizedBox(height: 16),
            TextField(
              controller: _controller,
              autofocus: true,
              keyboardType: TextInputType.number,
              textAlign: TextAlign.center,
              maxLength: 6,
              inputFormatters: [FilteringTextInputFormatter.digitsOnly],
              onChanged: (_) => setState(() {}),
              onSubmitted: (_) => _submit(),
              decoration: const InputDecoration(
                counterText: '',
                hintText: '000000',
                border: OutlineInputBorder(),
              ),
              style: Theme.of(context).textTheme.headlineMedium?.copyWith(
                letterSpacing: 10,
                fontFeatures: const [FontFeature.tabularFigures()],
              ),
            ),
            const SizedBox(height: 16),
            FilledButton(
              onPressed: _controller.text.length == 6 ? _submit : null,
              child: const Text('配对'),
            ),
          ],
        ),
      ),
    );
  }
}
