"""
Sample Calculator Module
A simple example file you can upload to test documentation generation.
"""


def add(a: float, b: float) -> float:
    """Add two numbers and return the result."""
    return a + b


def subtract(a: float, b: float) -> float:
    """Subtract b from a and return the result."""
    return a - b


def multiply(a: float, b: float) -> float:
    """Multiply two numbers and return the result."""
    return a * b


def divide(a: float, b: float) -> float:
    """
    Divide a by b and return the result.
    Raises ValueError if b is zero.
    """
    if b == 0:
        raise ValueError("Cannot divide by zero")
    return a / b


class Calculator:
    """A simple calculator class with basic operations."""

    def __init__(self):
        self.history = []

    def calculate(self, operation: str, a: float, b: float) -> float:
        """
        Perform a calculation and store it in history.

        Args:
            operation: One of 'add', 'subtract', 'multiply', 'divide'
            a: First number
            b: Second number

        Returns:
            Result of the calculation
        """
        operations = {
            "add": add,
            "subtract": subtract,
            "multiply": multiply,
            "divide": divide,
        }

        if operation not in operations:
            raise ValueError(f"Unknown operation: {operation}")

        result = operations[operation](a, b)
        self.history.append(f"{operation}({a}, {b}) = {result}")
        return result

    def get_history(self) -> list:
        """Return the list of past calculations."""
        return self.history

    def clear_history(self) -> None:
        """Clear the calculation history."""
        self.history = []


if __name__ == "__main__":
    calc = Calculator()
    print(calc.calculate("add", 5, 3))
    print(calc.calculate("multiply", 4, 7))
    print(calc.get_history())
