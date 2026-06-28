# Third-Party Notices

`llm-wiki-md-cli` is distributed under the MIT License (see `LICENSE`).

The built CLI artifact `tools/wiki.pyz` bundles one third-party package so the
zipapp can run with no external dependencies. Its license is reproduced below in
full, as required.

The pure-Python JSON Schema validator at
`tools/wiki-src/wikicli/core/_minijsonschema.py` is original code written for
this project from the JSON Schema Draft-07 specification; it is not derived from
any third-party implementation and is covered by this project's MIT License.

---

## portalocker

- Version bundled: 3.2.0
- Homepage: https://github.com/WoLpH/portalocker
- License: BSD 3-Clause
- Used as: an optional cross-platform file-locking accelerator. The CLI also
  works without it, falling back to the Python standard library (`fcntl` /
  `msvcrt`).

```
Copyright 2022 Rick van Hattem

Redistribution and use in source and binary forms, with or without modification, are permitted provided that the following conditions are met:

1. Redistributions of source code must retain the above copyright notice, this list of conditions and the following disclaimer.

2. Redistributions in binary form must reproduce the above copyright notice, this list of conditions and the following disclaimer in the documentation and/or other materials provided with the distribution.

3. Neither the name of the copyright holder nor the names of its contributors may be used to endorse or promote products derived from this software without specific prior written permission.

THIS SOFTWARE IS PROVIDED BY THE COPYRIGHT HOLDERS AND CONTRIBUTORS "AS IS" AND ANY EXPRESS OR IMPLIED WARRANTIES, INCLUDING, BUT NOT LIMITED TO, THE IMPLIED WARRANTIES OF MERCHANTABILITY AND FITNESS FOR A PARTICULAR PURPOSE ARE DISCLAIMED. IN NO EVENT SHALL THE COPYRIGHT HOLDER OR CONTRIBUTORS BE LIABLE FOR ANY DIRECT, INDIRECT, INCIDENTAL, SPECIAL, EXEMPLARY, OR CONSEQUENTIAL DAMAGES (INCLUDING, BUT NOT LIMITED TO, PROCUREMENT OF SUBSTITUTE GOODS OR SERVICES; LOSS OF USE, DATA, OR PROFITS; OR BUSINESS INTERRUPTION) HOWEVER CAUSED AND ON ANY THEORY OF LIABILITY, WHETHER IN CONTRACT, STRICT LIABILITY, OR TORT (INCLUDING NEGLIGENCE OR OTHERWISE) ARISING IN ANY WAY OUT OF THE USE OF THIS SOFTWARE, EVEN IF ADVISED OF THE POSSIBILITY OF SUCH DAMAGE.
```
