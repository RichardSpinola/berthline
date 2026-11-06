public abstract class Pet {
    private final String name;
    private int age;

    public Pet(String name) {
        this.name = name;
    }

    public abstract String sound();
}
