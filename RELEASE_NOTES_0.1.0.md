# eDocAPI 0.1.0

## Highlights

- Add a built-in developer dashboard at `/` with your registered routes,
  supported document formats, upload limit, and document operations.
- Preserve custom `GET /` handlers and allow the dashboard to be disabled with
  `App(dashboard=False)`.
- Add dashboard startup guidance to the README.

## Compatibility

This is an alpha release. Existing document conversion APIs and optional
dependency groups remain unchanged. The dashboard is shown only when an app
does not define its own `GET /` route.

## TestPyPI candidate

This release note describes a TestPyPI candidate for validating package build
and installation. It is not a production PyPI announcement.
