#define PY_SSIZE_T_CLEAN
#include <Python.h>
#include <mach-o/dyld.h>
#include <errno.h>
#include <fcntl.h>
#include <limits.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/stat.h>
#include <sys/wait.h>
#include <unistd.h>

#define DISPLAY_NAME "Jelly Dict"

static int join_path(char *out, size_t out_size, const char *left, const char *right) {
  int written = snprintf(out, out_size, "%s/%s", left, right);
  return written >= 0 && written < (int)out_size ? 0 : -1;
}

static int read_first_line(const char *path, char *out, size_t out_size) {
  FILE *file = fopen(path, "r");
  if (file == NULL) {
    return -1;
  }
  if (fgets(out, (int)out_size, file) == NULL) {
    fclose(file);
    return -1;
  }
  fclose(file);
  out[strcspn(out, "\r\n")] = '\0';
  return out[0] == '\0' ? -1 : 0;
}

static int ensure_parent_dir(const char *path) {
  char copy[PATH_MAX];
  if (snprintf(copy, sizeof(copy), "%s", path) >= (int)sizeof(copy)) {
    return -1;
  }
  char *slash = strrchr(copy, '/');
  if (slash == NULL) {
    return -1;
  }
  *slash = '\0';
  for (char *cursor = copy + 1; *cursor != '\0'; cursor++) {
    if (*cursor != '/') {
      continue;
    }
    *cursor = '\0';
    if (mkdir(copy, 0755) != 0 && errno != EEXIST) {
      return -1;
    }
    *cursor = '/';
  }
  return mkdir(copy, 0755) == 0 || errno == EEXIST ? 0 : -1;
}

static void append_log_header(const char *log_file, const char *title) {
  ensure_parent_dir(log_file);
  int fd = open(log_file, O_WRONLY | O_CREAT | O_APPEND, 0644);
  if (fd < 0) {
    return;
  }
  dprintf(fd, "\n## %s\n", title);
  dprintf(fd, "launcher: native embedded Python\n");
  close(fd);
}

static int run_quickstart(const char *repo_root, const char *script, const char *log_file, const char *arg) {
  ensure_parent_dir(log_file);
  int fd = open(log_file, O_WRONLY | O_CREAT | O_APPEND, 0644);
  if (fd < 0) {
    return 1;
  }

  pid_t pid = fork();
  if (pid < 0) {
    close(fd);
    return 1;
  }

  if (pid == 0) {
    dup2(fd, STDOUT_FILENO);
    dup2(fd, STDERR_FILENO);
    close(fd);
    chdir(repo_root);
    execl(script, script, arg, (char *)NULL);
    _exit(127);
  }

  close(fd);
  int status = 0;
  if (waitpid(pid, &status, 0) < 0) {
    return 1;
  }
  return WIFEXITED(status) ? WEXITSTATUS(status) : 1;
}

static void show_message(const char *message) {
  pid_t pid = fork();
  if (pid != 0) {
    if (pid > 0) {
      int status = 0;
      waitpid(pid, &status, 0);
    }
    return;
  }

  execl(
    "/usr/bin/osascript",
    "osascript",
    "-e",
    "on run argv\n"
    "display dialog (item 1 of argv) with title \"Jelly Dict\" buttons {\"OK\"} default button \"OK\"\n"
    "end run",
    "--",
    message,
    (char *)NULL
  );
  _exit(127);
}

static int prepend_path(const char *bin_dir) {
  const char *old_path = getenv("PATH");
  char path[PATH_MAX * 2];
  int written = snprintf(path, sizeof(path), "%s%s%s", bin_dir, old_path ? ":" : "", old_path ? old_path : "");
  if (written < 0 || written >= (int)sizeof(path)) {
    return -1;
  }
  return setenv("PATH", path, 1);
}

static int initialize_python(const char *venv_python) {
  PyStatus status;
  PyConfig config;
  char *argv[] = {DISPLAY_NAME, NULL};

  PyConfig_InitPythonConfig(&config);
  config.parse_argv = 0;
  status = PyConfig_SetBytesString(&config, &config.program_name, venv_python);
  if (PyStatus_Exception(status)) {
    PyConfig_Clear(&config);
    Py_ExitStatusException(status);
  }
  status = PyConfig_SetBytesString(&config, &config.executable, venv_python);
  if (PyStatus_Exception(status)) {
    PyConfig_Clear(&config);
    Py_ExitStatusException(status);
  }
  status = PyConfig_SetBytesArgv(&config, 1, argv);
  if (PyStatus_Exception(status)) {
    PyConfig_Clear(&config);
    Py_ExitStatusException(status);
  }

  status = Py_InitializeFromConfig(&config);
  PyConfig_Clear(&config);
  if (PyStatus_Exception(status)) {
    Py_ExitStatusException(status);
  }
  return 0;
}

static int run_app_main(const char *app_dir) {
  if (chdir(app_dir) != 0) {
    perror("chdir app_dir");
    return 1;
  }

  PyObject *sys_path = PySys_GetObject("path");
  PyObject *path = PyUnicode_FromString(app_dir);
  if (sys_path == NULL || path == NULL || PyList_Insert(sys_path, 0, path) != 0) {
    Py_XDECREF(path);
    PyErr_Print();
    return 1;
  }
  Py_DECREF(path);

  PyObject *module = PyImport_ImportModule("app.main");
  if (module == NULL) {
    PyErr_Print();
    return 1;
  }

  PyObject *main_func = PyObject_GetAttrString(module, "main");
  Py_DECREF(module);
  if (main_func == NULL || !PyCallable_Check(main_func)) {
    Py_XDECREF(main_func);
    PyErr_Print();
    return 1;
  }

  PyObject *result = PyObject_CallNoArgs(main_func);
  Py_DECREF(main_func);
  if (result == NULL) {
    PyErr_Print();
    return 1;
  }

  long exit_code = PyLong_AsLong(result);
  Py_DECREF(result);
  if (PyErr_Occurred()) {
    PyErr_Print();
    return 1;
  }
  return (int)exit_code;
}

int main(void) {
  char executable[PATH_MAX];
  char resolved[PATH_MAX];
  char resources[PATH_MAX];
  char repo_path_file[PATH_MAX];
  char repo_root[PATH_MAX];
  char app_dir[PATH_MAX];
  char venv_dir[PATH_MAX];
  char venv_bin[PATH_MAX];
  char venv_python[PATH_MAX];
  char quickstart_script[PATH_MAX];
  char log_file[PATH_MAX];
  uint32_t size = sizeof(executable);

  if (_NSGetExecutablePath(executable, &size) != 0) {
    fprintf(stderr, "Unable to locate executable path.\n");
    return 1;
  }

  if (realpath(executable, resolved) == NULL) {
    perror("realpath");
    return 1;
  }

  char *slash = strrchr(resolved, '/');
  if (slash == NULL) {
    fprintf(stderr, "Unexpected executable path.\n");
    return 1;
  }
  *slash = '\0';

  if (join_path(resources, sizeof(resources), resolved, "../Resources") != 0 ||
      join_path(repo_path_file, sizeof(repo_path_file), resources, "repo_path.txt") != 0 ||
      read_first_line(repo_path_file, repo_root, sizeof(repo_root)) != 0 ||
      join_path(app_dir, sizeof(app_dir), repo_root, "app_files/jelly_dict") != 0 ||
      join_path(venv_dir, sizeof(venv_dir), app_dir, ".venv") != 0 ||
      join_path(venv_bin, sizeof(venv_bin), venv_dir, "bin") != 0 ||
      join_path(venv_python, sizeof(venv_python), venv_bin, "python") != 0 ||
      join_path(quickstart_script, sizeof(quickstart_script), repo_root, "app_files/scripts/quickstart.sh") != 0 ||
      join_path(log_file, sizeof(log_file), app_dir, ".jelly_dict/logs/quickstart.log") != 0) {
    show_message("앱 실행 경로가 너무 깁니다. repo 위치를 더 짧은 경로로 옮긴 뒤 다시 설치해 주세요.");
    return 1;
  }

  append_log_header(log_file, "app launcher check");
  if (run_quickstart(repo_root, quickstart_script, log_file, "--check") != 0) {
    append_log_header(log_file, "app launcher repair");
    if (run_quickstart(repo_root, quickstart_script, log_file, "--accept-license") != 0) {
      show_message("앱 실행 전 환경 복구에 실패했습니다.\n\nInstall jelly dict.command를 다시 실행해 주세요.\n\n로그: app_files/jelly_dict/.jelly_dict/logs/quickstart.log");
      return 1;
    }
  }

  if (access(venv_python, X_OK) != 0) {
    show_message("전용 Python 환경을 찾지 못했습니다.\n\nInstall jelly dict.command를 다시 실행해 주세요.");
    return 1;
  }

  setenv("JELLY_DICT_APP_BUNDLE", "1", 1);
  setenv("JELLY_DICT_APP_DIR", app_dir, 1);
  setenv("JELLY_DICT_PYTHON", venv_python, 1);
  setenv("VIRTUAL_ENV", venv_dir, 1);
  setenv("PYTHONNOUSERSITE", "1", 1);
  prepend_path(venv_bin);

  initialize_python(venv_python);
  int exit_code = run_app_main(app_dir);
  if (Py_FinalizeEx() < 0 && exit_code == 0) {
    exit_code = 120;
  }
  return exit_code;
}
