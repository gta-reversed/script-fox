# Setup
1. You'll need:
    - [Python](https://www.python.org/) (3.12 or newer)
    - [Poetry](https://python-poetry.org/docs/)

2. Install dependencies:
    ```sh
    poetry install
    ```
3. Profit

# Usage

### Operating modes
1. Generate stubs and `REGISTER_` calls for commands matching the criteria and write them to a new file (Specified by `--output`, or `output.cpp` by default)
    ```sh
    poetry run python -m app --klass <klass_name> --generate-register-calls
    ```
2. Update existing file with docs, missing handlers and `REGISTER_` calls by providing the `--input` argument with the file to update, if no `--output` is provided, the input file will be updated in place.
    ```sh
    poetry run python -m app --input <file_to_update> --klass <klass_name> --generate-register-calls
    ```
    Missing command handlers and `REGISTER_` calls for all commands matching the criteria will  be added to the file, and missing docs will be added to existing handlers.


### Command filters
You can filter commands to be processed using:
- `--klass` to regex match class names (e.g. `--klass ^Char$` to match only `Char`)
- `--name` to regex match command names (e.g. `--name ^GET_` to match only commands starting with `GET_`)
- `--extension` to regex match extension names (See [here](https://library.sannybuilder.com/#/sa/script/extensions) for available extensions - by default `default` is used, which includes commands from vanilla SA only)

### Other options
See `--help` for a full list of options

### Examples
1. Generate stubs for all commands in the `Char` class and write them to `char_stubs.cpp`:
    ```sh
    poetry run python -m app --klass Char --output char_stubs.cpp
    ```
2. Update `char_stubs.cpp` in-place with missing docs, stubs and `REGISTER_` calls for all commands in the `Char` class:
    ```sh
    poetry run python -m app --input char_stubs.cpp --klass Char --generate-register-calls
    ```

For convenience the `./script-fox.sh` script is provided to run the app without having to prefix commands with `poetry run python -m app`.
