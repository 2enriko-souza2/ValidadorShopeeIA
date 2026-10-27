import os
import sys

# Garante que a pasta 'src' esteja no caminho de pacotes (equivalente ao classpath do Java)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from view.TelaPrincipal import ValidadorExpedicaoApp


def main():
    app = ValidadorExpedicaoApp()
    app.mainloop()


if __name__ == "__main__":
    main()
