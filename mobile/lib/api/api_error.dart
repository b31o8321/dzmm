class ApiError implements Exception {
  const ApiError({required this.code, required this.message, this.statusCode});

  final String code;
  final String message;
  final int? statusCode;

  bool get isAuthenticationFailure =>
      code == 'unauthorized' || code == 'revoked';

  @override
  String toString() => 'ApiError(code: $code, statusCode: $statusCode)';
}
